"""Transparent five-component Trust Score engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .anomaly import AnomalyPrediction
from .config import TrustConfig
from .forecasting import ForecastPrediction
from .schema import Observation


@dataclass(frozen=True)
class ComponentScore:
    score: float | None
    available: bool
    explanation: str


@dataclass(frozen=True)
class TrustScoreResult:
    final_score: int
    components: dict[str, ComponentScore]
    weights: dict[str, float]
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "final_score": self.final_score,
            "components": {name: asdict(component) for name, component in self.components.items()},
            "weights": self.weights,
            "explanation": self.explanation,
        }


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def calculate_trust_score(
    observation: Observation,
    anomaly: AnomalyPrediction,
    forecast: ForecastPrediction | None,
    config: TrustConfig,
    as_of: datetime | None = None,
    cross_source_value: float | None = None,
    expected_interval_hours: float = 1.0,
) -> TrustScoreResult:
    as_of = (as_of or observation.received_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    components: dict[str, ComponentScore] = {}

    if observation.value_m is None:
        completeness = ComponentScore(0.0, True, "Required water-level observation is missing.")
    elif observation.is_imputed:
        completeness = ComponentScore(55.0, True, "Value is imputed and is not an observed fact.")
    else:
        completeness = ComponentScore(100.0, True, "Required observed water-level value is present.")
    components["completeness"] = completeness

    age_hours = max(0.0, (as_of - observation.timestamp).total_seconds() / 3600.0)
    if age_hours <= expected_interval_hours * 1.5:
        freshness_score = 100.0
    elif age_hours <= 6.0:
        freshness_score = 80.0 - (age_hours - expected_interval_hours * 1.5) * 10.0
    elif age_hours <= 24.0:
        freshness_score = 40.0 - (age_hours - 6.0) * (30.0 / 18.0)
    else:
        freshness_score = 0.0
    components["freshness"] = ComponentScore(
        _clamp(freshness_score), True, f"Reading age is {age_hours:.2f} hours."
    )

    severe_reasons = {"missing_observation", "out_of_range", "frozen_sensor", "stale_timestamp"}
    plausibility_score = 100.0
    if anomaly.is_anomaly:
        plausibility_score -= 55.0 if severe_reasons.intersection(anomaly.reasons) else 35.0
        plausibility_score -= 8.0 * max(0, len(anomaly.reasons) - 1)
    components["plausibility"] = ComponentScore(
        _clamp(plausibility_score),
        True,
        "No quality anomaly detected."
        if not anomaly.reasons
        else "Quality checks flagged: " + ", ".join(anomaly.reasons) + ".",
    )

    if observation.value_m is None or forecast is None:
        components["model_agreement"] = ComponentScore(
            None, False, "A validated forecast is unavailable for comparison."
        )
    else:
        half_width = max(1e-6, (forecast.upper_bound - forecast.lower_bound) / 2.0)
        deviation_units = abs(observation.value_m - forecast.predicted_value) / half_width
        agreement = 100.0 if deviation_units <= 1.0 else max(0.0, 100.0 - (deviation_units - 1.0) * 35.0)
        components["model_agreement"] = ComponentScore(
            _clamp(agreement),
            True,
            f"Observation is {deviation_units:.2f} calibrated interval half-widths from the forecast.",
        )

    if observation.value_m is None or cross_source_value is None:
        components["cross_source_consistency"] = ComponentScore(
            None, False, "No independent aligned observation was supplied; agreement is unknown."
        )
    else:
        difference = abs(observation.value_m - cross_source_value)
        scale = max(0.05, abs(observation.value_m) * 0.10)
        consistency = max(0.0, 100.0 - 50.0 * difference / scale)
        components["cross_source_consistency"] = ComponentScore(
            _clamp(consistency), True, f"Independent evidence differs by {difference:.3f} m."
        )

    total = 0.0
    for name, weight in config.weights.items():
        component = components[name]
        contribution = component.score if component.available and component.score is not None else config.unavailable_component_score
        total += weight * contribution
    if observation.value_m is None:
        total = min(total, 30.0)
    if "out_of_range" in anomaly.reasons:
        total = min(total, 35.0)
    final_score = int(round(_clamp(total)))
    unavailable = [name for name, component in components.items() if not component.available]
    explanation = f"Weighted Trust Score is {final_score}/100."
    if unavailable:
        explanation += " Unavailable evidence was conservatively scored for: " + ", ".join(unavailable) + "."
    return TrustScoreResult(
        final_score=final_score,
        components=components,
        weights=dict(config.weights),
        explanation=explanation,
    )

