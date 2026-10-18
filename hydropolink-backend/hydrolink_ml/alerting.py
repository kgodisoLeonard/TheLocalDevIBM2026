"""Trust-gated alert classification without invented public flood thresholds."""

from __future__ import annotations

from dataclasses import dataclass

from .anomaly import AnomalyPrediction
from .config import TrustConfig
from .forecasting import ForecastPrediction
from .trust import TrustScoreResult


@dataclass(frozen=True)
class AlertDecision:
    risk_level: str
    alert_status: str
    requires_human_review: bool
    automatic_public_warning: bool
    reason: str


def decide_alert(
    trust: TrustScoreResult,
    anomaly: AnomalyPrediction,
    forecast: ForecastPrediction | None,
    trust_config: TrustConfig,
    elevated_reference_m: float | None = None,
    authoritative_flood_threshold_m: float | None = None,
) -> AlertDecision:
    """Separate data quality from hazard risk and gate automation by trust."""
    reasons: list[str] = []
    risk_level = "normal"
    if forecast is not None and authoritative_flood_threshold_m is not None:
        if forecast.upper_bound >= authoritative_flood_threshold_m:
            risk_level = "flood_risk"
            reasons.append("forecast interval reaches the configured authoritative flood threshold")
    elif forecast is not None and elevated_reference_m is not None and forecast.upper_bound >= elevated_reference_m:
        risk_level = "caution"
        reasons.append("forecast is elevated relative to the model training distribution")
    if anomaly.is_anomaly:
        reasons.append("measurement-quality checks require attention")
    if not reasons:
        reasons.append("no configured hazard threshold or quality rule was triggered")

    high_trust = trust.final_score >= trust_config.automatic_alert_min_trust
    warning = risk_level in {"caution", "flood_risk"}
    automatic = bool(warning and high_trust and authoritative_flood_threshold_m is not None)
    requires_review = bool(not high_trust or anomaly.is_anomaly or (warning and not automatic))
    if automatic:
        status = "automatic_alert_eligible"
    elif requires_review:
        status = "human_review_required"
    else:
        status = "normal"
    return AlertDecision(
        risk_level=risk_level,
        alert_status=status,
        requires_human_review=requires_review,
        automatic_public_warning=automatic,
        reason="; ".join(reasons).capitalize() + ".",
    )

