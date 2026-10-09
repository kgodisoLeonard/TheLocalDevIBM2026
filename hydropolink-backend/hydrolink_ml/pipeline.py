"""End-to-end offline training and held-out evaluation workflow."""

from __future__ import annotations

import platform
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import numpy as np
import sklearn

from .anomaly import evaluate_anomaly_rows, predict_anomaly, train_anomaly_bundle
from .artifacts import load_artifacts, save_artifacts
from .config import ARTIFACT_ROOT, DATA_ROOT, DEFAULT_CONFIG, REPORT_ROOT, PipelineConfig
from .features import build_feature_rows
from .forecasting import evaluate_forecasts, make_forecast_samples, predict_forecast, train_forecast_bundle
from .reporting import write_evaluation_report
from .schema import Observation, read_observations_csv, write_observations_csv
from .synthetic import chronological_split, generate_development_observations, inject_faults
from .trust import calculate_trust_score


def _period(observations: list[Observation]) -> str:
    if not observations:
        return "not available"
    timestamps = [item.timestamp for item in observations]
    return f"{min(timestamps).isoformat()} to {max(timestamps).isoformat()}"


def _history_payload(observations: Iterable[Observation], tail: int = 96) -> list[dict[str, object]]:
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.station_id].append(observation)
    return [
        observation.to_row()
        for station_items in grouped.values()
        for observation in sorted(station_items, key=lambda item: item.timestamp)[-tail:]
    ]


def _trust_validation(anomaly_bundle: Any, forecast_bundle: Any, test_rows: list[Any], test_samples: list[Any], config: PipelineConfig) -> dict[str, dict[str, float | int]]:
    forecast_by_target = {
        (sample.station_id, sample.target_timestamp): predict_forecast(forecast_bundle, sample.feature_row)
        for sample in test_samples
    }
    grouped_scores: dict[str, list[int]] = defaultdict(list)
    for row in test_rows:
        anomaly = predict_anomaly(anomaly_bundle, row)
        hindcast = forecast_by_target.get((row.station_id, row.timestamp))
        trust = calculate_trust_score(
            row.source_observation,
            anomaly,
            hindcast,
            config.trust,
            as_of=row.received_at,
            expected_interval_hours=config.feature.expected_interval_hours,
        )
        grouped_scores[row.source_observation.fault_type].append(trust.final_score)
    return {
        scenario: {
            "mean": float(mean(scores)),
            "min": int(min(scores)),
            "max": int(max(scores)),
            "samples": len(scores),
        }
        for scenario, scores in sorted(grouped_scores.items())
    }


def train_pipeline(
    input_csv: Path | None = None,
    artifact_directory: Path | None = None,
    report_directory: Path | None = None,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    started = time.perf_counter()
    if input_csv is None:
        clean = generate_development_observations(seed=config.random_seed)
        data_mode = "synthetic_development"
    else:
        clean = read_observations_csv(input_csv, source_default="historical_csv_import")
        data_mode = "authentic_import"
    train, validation_clean, test_clean = chronological_split(clean)
    validation_faulty = inject_faults(validation_clean, seed=config.random_seed + 100)
    test_faulty = inject_faults(test_clean, seed=config.random_seed + 200)

    synthetic_dir = DATA_ROOT / "synthetic"
    processed_dir = DATA_ROOT / "processed"
    if data_mode == "synthetic_development":
        write_observations_csv(synthetic_dir / "development_clean.csv", clean)
        write_observations_csv(synthetic_dir / "validation_faults.csv", validation_faulty)
        write_observations_csv(synthetic_dir / "test_faults.csv", test_faulty)
    write_observations_csv(processed_dir / "train_clean.csv", train)
    write_observations_csv(processed_dir / "validation_clean.csv", validation_clean)
    write_observations_csv(processed_dir / "test_clean.csv", test_clean)
    write_observations_csv(processed_dir / "validation_faulty.csv", validation_faulty)
    write_observations_csv(processed_dir / "test_faulty.csv", test_faulty)

    train_rows = build_feature_rows(train, config.feature)
    validation_rows = build_feature_rows(validation_faulty, config.feature)
    test_rows = build_feature_rows(test_faulty, config.feature)
    validation_clean_rows = build_feature_rows(validation_clean, config.feature)
    test_clean_rows = build_feature_rows(test_clean, config.feature)

    anomaly_bundle = train_anomaly_bundle(train_rows, validation_rows, config.anomaly, data_mode)
    anomaly_test = evaluate_anomaly_rows(anomaly_bundle, test_rows)
    train_samples = make_forecast_samples(train_rows, config.forecast.horizon_steps)
    validation_samples = make_forecast_samples(validation_clean_rows, config.forecast.horizon_steps)
    test_samples = make_forecast_samples(test_clean_rows, config.forecast.horizon_steps)
    forecast_bundle = train_forecast_bundle(train_samples, validation_samples, config.forecast, data_mode)
    forecast_test = evaluate_forecasts(forecast_bundle, test_samples)
    forecast_bundle.test_metrics = forecast_test
    trust_validation = _trust_validation(anomaly_bundle, forecast_bundle, test_rows, test_samples, config)

    artifact_directory = artifact_directory or ARTIFACT_ROOT / "current"
    report_directory = report_directory or REPORT_ROOT
    sources = sorted({item.source for item in clean})
    station_ids = sorted({item.station_id for item in clean})
    real_count = sum(not item.source.startswith("synthetic_") for item in clean)
    synthetic_count = len(clean) - real_count
    metadata = {
        "model_id": config.model_id,
        "model_version": config.model_version,
        "algorithm": {
            "anomaly": "station Isolation Forest plus deterministic rolling checks",
            "forecast": {station: model.algorithm for station, model in forecast_bundle.station_models.items()},
        },
        "data_mode": data_mode,
        "data_sources": sources,
        "station_coverage": station_ids,
        "feature_schema": list(anomaly_bundle.feature_names),
        "training_period": _period(train),
        "validation_period": _period(validation_clean),
        "test_period": _period(test_clean),
        "random_seed": config.random_seed,
        "configuration": config.to_dict(),
        "validation_metrics": {"anomaly": anomaly_bundle.validation_metrics},
        "test_metrics": {"anomaly": anomaly_test, "forecast": forecast_test},
        "dependencies": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }
    manifest = save_artifacts(
        artifact_directory,
        anomaly_bundle,
        forecast_bundle,
        metadata,
        # The model is trained only on the training period.  The latest clean
        # observations are persisted solely as operational inference context.
        _history_payload(clean),
    )
    training_seconds = time.perf_counter() - started

    load_started = time.perf_counter()
    loaded = load_artifacts(artifact_directory)
    loading_ms = (time.perf_counter() - load_started) * 1000.0
    benchmark_rows = test_rows[: min(500, len(test_rows))]
    inference_started = time.perf_counter()
    for row in benchmark_rows:
        anomaly = predict_anomaly(loaded.anomaly, row)
        forecast = predict_forecast(loaded.forecast, row)
        calculate_trust_score(row.source_observation, anomaly, forecast, config.trust, as_of=row.received_at)
    elapsed = time.perf_counter() - inference_started
    mean_latency_ms = elapsed * 1000.0 / max(1, len(benchmark_rows))
    artifact_bytes = sum(item["bytes"] for item in manifest["files"].values())
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    results = {
        "run_id": run_id,
        "dataset": {
            "data_mode": data_mode,
            "sources": sources,
            "stations": len(station_ids),
            "station_ids": station_ids,
            "total_observations": len(clean),
            "real_observations": real_count,
            "synthetic_observations": synthetic_count,
            "train_observations": len(train),
            "validation_observations": len(validation_clean),
            "test_observations": len(test_clean),
            "training_period": _period(train),
            "validation_period": _period(validation_clean),
            "test_period": _period(test_clean),
        },
        "configuration": config.to_dict(),
        "anomaly_validation": anomaly_bundle.validation_metrics,
        "anomaly_test": anomaly_test,
        "forecast_test": forecast_test,
        "trust_validation": trust_validation,
        "runtime": {
            "training_seconds": training_seconds,
            "loading_milliseconds": loading_ms,
            "mean_inference_milliseconds": mean_latency_ms,
            "predictions_per_second": 1000.0 / mean_latency_ms if mean_latency_ms > 0 else None,
            "artifact_bytes": artifact_bytes,
        },
        "limitations": [
            "The executed development run uses synthetic hydrological series unless an authentic canonical CSV is explicitly supplied.",
            "Synthetic results demonstrate pipeline behaviour and must not be represented as operational DWS/SAWS performance.",
            "No authoritative station flood thresholds are bundled; automatic public flood warnings remain disabled by default.",
            "SAWS rainfall archives require an authorised data request; synthetic rainfall is used only in development mode.",
            "Forecast intervals are calibrated from validation residuals and require recalibration for every authentic station deployment.",
        ],
    }
    write_evaluation_report(report_directory, results)
    return results


def evaluate_saved_pipeline(
    artifact_directory: Path | None = None,
    processed_directory: Path | None = None,
    config: PipelineConfig = DEFAULT_CONFIG,
) -> dict[str, object]:
    artifact_directory = artifact_directory or ARTIFACT_ROOT / "current"
    processed_directory = processed_directory or DATA_ROOT / "processed"
    loaded = load_artifacts(artifact_directory)
    faulty = read_observations_csv(processed_directory / "test_faulty.csv")
    clean = read_observations_csv(processed_directory / "test_clean.csv")
    anomaly_rows = build_feature_rows(faulty, config.feature)
    forecast_rows = build_feature_rows(clean, config.feature)
    samples = make_forecast_samples(forecast_rows, config.forecast.horizon_steps)
    return {
        "anomaly_test": evaluate_anomaly_rows(loaded.anomaly, anomaly_rows),
        "forecast_test": evaluate_forecasts(loaded.forecast, samples),
    }

