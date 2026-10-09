"""Isolation Forest plus deterministic hydrological quality checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.preprocessing import StandardScaler

from .config import AnomalyConfig
from .features import FEATURE_NAMES, FeatureRow, feature_matrix


@dataclass
class StationAnomalyModel:
    station_id: str
    scaler: StandardScaler
    model: IsolationForest
    score_threshold: float
    rate_threshold: float
    training_samples: int


@dataclass
class AnomalyBundle:
    feature_names: tuple[str, ...]
    station_models: dict[str, StationAnomalyModel]
    pooled_model: StationAnomalyModel | None
    z_threshold: float
    config: AnomalyConfig
    data_mode: str
    validation_metrics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AnomalyPrediction:
    is_anomaly: bool
    reasons: tuple[str, ...]
    isolation_score: float | None
    model_scope: str


def _fit_one(station_id: str, rows: list[FeatureRow], config: AnomalyConfig) -> StationAnomalyModel:
    matrix = feature_matrix(rows)
    scaler = StandardScaler()
    scaled = scaler.fit_transform(matrix)
    model = IsolationForest(
        n_estimators=220,
        contamination=config.contamination,
        random_state=config.random_seed,
        n_jobs=-1,
    )
    model.fit(scaled)
    scores = model.decision_function(scaled)
    rate_values = np.abs([row.values["rate_per_hour"] for row in rows])
    return StationAnomalyModel(
        station_id=station_id,
        scaler=scaler,
        model=model,
        score_threshold=float(np.quantile(scores, 0.025)),
        rate_threshold=max(0.05, float(np.quantile(rate_values, 0.995))),
        training_samples=len(rows),
    )


def train_anomaly_bundle(
    train_rows: Iterable[FeatureRow],
    validation_rows: Iterable[FeatureRow],
    config: AnomalyConfig,
    data_mode: str,
) -> AnomalyBundle:
    clean_train = [
        row
        for row in train_rows
        if row.source_observation.fault_type == "normal" and row.source_observation.value_m is not None
    ]
    if len(clean_train) < config.minimum_station_samples:
        raise ValueError("insufficient clean rows to train anomaly detector")
    grouped: dict[str, list[FeatureRow]] = {}
    for row in clean_train:
        grouped.setdefault(row.station_id, []).append(row)
    station_models = {
        station_id: _fit_one(station_id, rows, config)
        for station_id, rows in grouped.items()
        if len(rows) >= config.minimum_station_samples
    }
    pooled_model = _fit_one("__pooled__", clean_train, config)
    bundle = AnomalyBundle(
        feature_names=FEATURE_NAMES,
        station_models=station_models,
        pooled_model=pooled_model,
        z_threshold=3.5,
        config=config,
        data_mode=data_mode,
    )
    validation = list(validation_rows)
    best: tuple[float, float, float] | None = None
    for z_threshold in config.z_threshold_candidates:
        for quantile in config.isolation_quantile_candidates:
            for model in [*station_models.values(), pooled_model]:
                if model is None:
                    continue
                # Quantiles are taken only from normal training scores.
                source_rows = grouped.get(model.station_id, clean_train)
                training_scores = model.model.decision_function(model.scaler.transform(feature_matrix(source_rows)))
                model.score_threshold = float(np.quantile(training_scores, quantile))
            bundle.z_threshold = z_threshold
            metrics = evaluate_anomaly_rows(bundle, validation)
            f1 = float(metrics["f1"])
            false_positive_rate = float(metrics["false_positive_rate"])
            candidate = (f1, -false_positive_rate, quantile)
            if best is None or candidate > best:
                best = candidate
                best_thresholds = (
                    z_threshold,
                    {key: value.score_threshold for key, value in station_models.items()},
                    pooled_model.score_threshold if pooled_model else 0.0,
                )
    if best is None:
        raise ValueError("validation rows are required for threshold tuning")
    bundle.z_threshold = best_thresholds[0]
    for station_id, threshold in best_thresholds[1].items():
        bundle.station_models[station_id].score_threshold = threshold
    if bundle.pooled_model:
        bundle.pooled_model.score_threshold = best_thresholds[2]
    bundle.validation_metrics = evaluate_anomaly_rows(bundle, validation)
    return bundle


def predict_anomaly(bundle: AnomalyBundle, row: FeatureRow) -> AnomalyPrediction:
    reasons: list[str] = []
    observation = row.source_observation
    value = observation.value_m
    if value is None:
        reasons.append("missing_observation")
    else:
        if value < bundle.config.physical_min_m or value > bundle.config.physical_max_m:
            reasons.append("out_of_range")
        if abs(row.values["deviation_z_24"]) >= bundle.z_threshold:
            reasons.append("rolling_z_score")
        if abs(row.values["robust_deviation_24"]) >= bundle.config.robust_z_threshold:
            reasons.append("robust_deviation")
        if row.values["repeated_duration_hours"] >= bundle.config.frozen_hours:
            reasons.append("frozen_sensor")
    if (row.received_at - row.timestamp).total_seconds() / 3600.0 >= bundle.config.stale_hours:
        reasons.append("stale_timestamp")

    model = bundle.station_models.get(row.station_id) or bundle.pooled_model
    isolation_score: float | None = None
    scope = "unavailable"
    if model is not None:
        scope = "station" if row.station_id in bundle.station_models else "pooled"
        array = row.as_array(bundle.feature_names).reshape(1, -1)
        isolation_score = float(model.model.decision_function(model.scaler.transform(array))[0])
        if isolation_score < model.score_threshold:
            reasons.append("isolation_forest")
        if abs(row.values["rate_per_hour"]) > model.rate_threshold:
            reasons.append("rate_of_change")
    return AnomalyPrediction(
        is_anomaly=bool(reasons),
        reasons=tuple(dict.fromkeys(reasons)),
        isolation_score=isolation_score,
        model_scope=scope,
    )


def _binary_metrics(labels: list[int], predictions: list[int]) -> dict[str, object]:
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", zero_division=0
    )
    matrix = confusion_matrix(labels, predictions, labels=[0, 1])
    true_negative, false_positive, false_negative, true_positive = matrix.ravel()
    false_positive_rate = false_positive / max(1, false_positive + true_negative)
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "false_positive_rate": float(false_positive_rate),
        "confusion_matrix": {
            "true_negative": int(true_negative),
            "false_positive": int(false_positive),
            "false_negative": int(false_negative),
            "true_positive": int(true_positive),
        },
    }


def evaluate_anomaly_rows(bundle: AnomalyBundle, rows: Iterable[FeatureRow]) -> dict[str, object]:
    evaluated = list(rows)
    labels = [0 if row.source_observation.fault_type == "normal" else 1 for row in evaluated]
    predictions = [int(predict_anomaly(bundle, row).is_anomaly) for row in evaluated]
    overall = _binary_metrics(labels, predictions)
    by_fault: dict[str, dict[str, float | int]] = {}
    fault_names = sorted({row.source_observation.fault_type for row in evaluated if row.source_observation.fault_type != "normal"})
    for fault in fault_names:
        indices = [index for index, row in enumerate(evaluated) if row.source_observation.fault_type == fault]
        detected = sum(predictions[index] for index in indices)
        by_fault[fault] = {
            "samples": len(indices),
            "recall": detected / max(1, len(indices)),
        }
    by_station: dict[str, dict[str, object]] = {}
    for station_id in sorted({row.station_id for row in evaluated}):
        indices = [index for index, row in enumerate(evaluated) if row.station_id == station_id]
        by_station[station_id] = _binary_metrics(
            [labels[index] for index in indices], [predictions[index] for index in indices]
        )
    overall["samples"] = len(evaluated)
    overall["by_fault"] = by_fault
    overall["by_station"] = by_station
    return overall

