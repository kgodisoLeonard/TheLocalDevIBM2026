"""Low-latency inference facade used by FastAPI and the CLI."""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .alerting import decide_alert
from .anomaly import AnomalyPrediction, predict_anomaly
from .artifacts import LoadedArtifacts, load_artifacts
from .config import DEFAULT_CONFIG
from .features import FeatureRow, build_feature_rows
from .forecasting import ForecastPrediction, predict_forecast
from .schema import Observation, parse_timestamp
from .trust import calculate_trust_score


class HydroLinkInferenceService:
    """Load validated artifacts once and perform inference without retraining."""

    def __init__(self, artifact_directory: Path):
        self.artifact_directory = Path(artifact_directory)
        self.loaded: LoadedArtifacts | None = None
        self.load_error: str | None = None
        self.history: dict[str, list[Observation]] = {}
        try:
            self.loaded = load_artifacts(self.artifact_directory)
            for row in self.loaded.history_rows:
                observation = Observation.from_mapping(row, source_default="artifact_history")
                self.history.setdefault(observation.station_id, []).append(observation)
            for items in self.history.values():
                items.sort(key=lambda item: item.timestamp)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            self.load_error = str(exc)

    @property
    def available(self) -> bool:
        return self.loaded is not None

    def model_information(self) -> dict[str, object]:
        if self.loaded is None:
            return {"available": False, "error": self.load_error, "training_on_startup": False}
        metadata = self.loaded.metadata
        return {
            "available": True,
            "model_id": metadata.get("model_id"),
            "model_version": metadata.get("model_version"),
            "data_mode": metadata.get("data_mode"),
            "data_sources": metadata.get("data_sources"),
            "station_coverage": metadata.get("station_coverage"),
            "training_period": metadata.get("training_period"),
            "test_metrics": metadata.get("test_metrics"),
            "training_on_startup": False,
        }

    def _feature_context(self, observation: Observation) -> tuple[list[FeatureRow], str | None]:
        history = list(self.history.get(observation.station_id, []))
        if not history:
            return [], "no station-specific history is available"
        latest = history[-1]
        gap_hours = (observation.timestamp - latest.timestamp).total_seconds() / 3600.0
        if gap_hours < 0:
            return [], "reading predates the validated model history"
        # Discontinuous data must not silently produce a time-series forecast.
        if gap_hours > DEFAULT_CONFIG.feature.expected_interval_hours * 3:
            return [], f"history gap of {gap_hours:.1f} hours exceeds the supported continuity limit"
        rows = build_feature_rows([*history, observation], DEFAULT_CONFIG.feature)
        return rows, None if rows else "insufficient feature history"

    def analyze(
        self,
        station_id: str,
        name: str,
        value_m: float | None,
        timestamp: str | datetime,
        source: str,
        received_at: str | datetime | None = None,
        cross_source_value: float | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        parsed_timestamp = parse_timestamp(timestamp)
        observation = Observation(
            station_id=station_id,
            timestamp=parsed_timestamp,
            received_at=parse_timestamp(received_at) if received_at else parsed_timestamp,
            value_m=value_m,
            source=source,
        )
        rows, context_error = self._feature_context(observation) if self.loaded else ([], self.load_error)
        current_row = rows[-1] if rows else None
        if self.loaded and current_row:
            anomaly = predict_anomaly(self.loaded.anomaly, current_row)
            future_forecast = predict_forecast(self.loaded.forecast, current_row)
        else:
            reasons: list[str] = []
            if value_m is None:
                reasons.append("missing_observation")
            elif value_m < DEFAULT_CONFIG.anomaly.physical_min_m or value_m > DEFAULT_CONFIG.anomaly.physical_max_m:
                reasons.append("out_of_range")
            reasons.append("model_unavailable")
            anomaly = AnomalyPrediction(True, tuple(reasons), None, "unavailable")
            future_forecast = None
        if source.startswith("synthetic_") or source.startswith("cached_"):
            anomaly = AnomalyPrediction(
                True,
                tuple(dict.fromkeys([*anomaly.reasons, "non_authentic_source"])),
                anomaly.isolation_score,
                anomaly.model_scope,
            )

        # Model agreement needs a forecast issued before this observation, not
        # the future forecast issued from the observation itself.
        agreement_forecast: ForecastPrediction | None = None
        horizon = self.loaded.forecast.horizon_steps if self.loaded else 0
        if self.loaded and current_row and len(rows) > horizon:
            prior_row = rows[-(horizon + 1)]
            expected_delta = horizon * DEFAULT_CONFIG.feature.expected_interval_hours
            actual_delta = (current_row.timestamp - prior_row.timestamp).total_seconds() / 3600.0
            if math.isclose(actual_delta, expected_delta, rel_tol=0.05, abs_tol=0.1):
                agreement_forecast = predict_forecast(self.loaded.forecast, prior_row)

        now = as_of or observation.received_at or datetime.now(timezone.utc)
        trust = calculate_trust_score(
            observation,
            anomaly,
            agreement_forecast,
            DEFAULT_CONFIG.trust,
            as_of=now,
            cross_source_value=cross_source_value,
            expected_interval_hours=DEFAULT_CONFIG.feature.expected_interval_hours,
        )
        station_model = self.loaded.forecast.station_models.get(observation.station_id) if self.loaded else None
        elevated_reference = station_model.upper_data_bound if station_model else None
        alert = decide_alert(
            trust,
            anomaly,
            future_forecast,
            DEFAULT_CONFIG.trust,
            elevated_reference_m=elevated_reference,
            authoritative_flood_threshold_m=None,
        )

        if current_row:
            historical_values = [item.value_m for item in self.history.get(observation.station_id, [])[-24:] if item.value_m is not None]
            center = mean(historical_values) if historical_values else value_m or 0.0
            spread = pstdev(historical_values) if len(historical_values) > 1 else 0.0
            expected_range = f"{max(0.0, center - 2 * spread):.2f}m - {center + 2 * spread:.2f}m"
        else:
            expected_range = "unavailable"
        if future_forecast:
            confidence_text = f"{future_forecast.lower_bound:.2f}m - {future_forecast.upper_bound:.2f}m"
            forecast_payload: dict[str, object] = {
                "predicted_level": round(future_forecast.predicted_value, 3),
                "confidence_interval": confidence_text,
                "lower_bound": round(future_forecast.lower_bound, 3),
                "upper_bound": round(future_forecast.upper_bound, 3),
                "coverage_target": future_forecast.interval_coverage_target,
                "horizon_hours": future_forecast.horizon_steps,
                "algorithm": future_forecast.algorithm,
                "model_available": True,
            }
        else:
            forecast_payload = {
                "predicted_level": None,
                "confidence_interval": "unavailable",
                "lower_bound": None,
                "upper_bound": None,
                "coverage_target": None,
                "horizon_hours": self.loaded.forecast.horizon_steps if self.loaded else None,
                "algorithm": None,
                "model_available": False,
                "unavailable_reason": context_error or "station forecast artifact is unavailable",
            }
        anomaly_explanation = (
            "No anomaly detected by the combined model and deterministic checks."
            if not anomaly.reasons
            else "Anomaly evidence: " + ", ".join(anomaly.reasons) + "."
        )
        model_metadata = self.model_information()
        return {
            "station_id": observation.station_id,
            "name": name,
            "catchment": f"Basin Zone {observation.station_id[:1]}",
            "timestamp": observation.timestamp.isoformat(),
            "source": source,
            "trust_score": trust.final_score,
            "trust_components": trust.to_dict()["components"],
            "trust_explanation": trust.explanation,
            "current_value": observation.value_m,
            "expected_range": expected_range,
            "status": "healthy" if not anomaly.is_anomaly and trust.final_score >= 70 else "review_required",
            "forecast": forecast_payload,
            "anomaly": anomaly.is_anomaly,
            "anomaly_reasons": list(anomaly.reasons),
            "anomalies_flagged": anomaly_explanation,
            "isolation_score": anomaly.isolation_score,
            "model_scope": anomaly.model_scope,
            "model_info": {
                "available": model_metadata.get("available"),
                "model_id": model_metadata.get("model_id"),
                "model_version": model_metadata.get("model_version"),
                "data_mode": model_metadata.get("data_mode"),
                "context_warning": context_error,
            },
            "alert": asdict(alert),
        }

