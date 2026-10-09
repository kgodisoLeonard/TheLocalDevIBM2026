"""Configuration used by training, evaluation, trust scoring and inference."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = BACKEND_ROOT.parent
DATA_ROOT = PROJECT_ROOT / "data"
ARTIFACT_ROOT = BACKEND_ROOT / "artifacts"
REPORT_ROOT = PROJECT_ROOT / "reports"


@dataclass(frozen=True)
class FeatureConfig:
    lag_steps: tuple[int, ...] = (1, 3, 6, 24)
    short_window: int = 6
    long_window: int = 24
    minimum_history: int = 24
    expected_interval_hours: float = 1.0


@dataclass(frozen=True)
class AnomalyConfig:
    contamination: float = 0.06
    minimum_station_samples: int = 120
    z_threshold_candidates: tuple[float, ...] = (2.5, 3.0, 3.5, 4.0)
    isolation_quantile_candidates: tuple[float, ...] = (0.01, 0.025, 0.05, 0.075)
    robust_z_threshold: float = 4.5
    frozen_hours: float = 6.0
    stale_hours: float = 6.0
    physical_min_m: float = 0.0
    physical_max_m: float = 30.0
    random_seed: int = 42


@dataclass(frozen=True)
class ForecastConfig:
    horizon_steps: int = 24
    minimum_station_samples: int = 180
    interval_coverage: float = 0.90
    random_seed: int = 42


@dataclass(frozen=True)
class TrustConfig:
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "completeness": 0.25,
            "freshness": 0.20,
            "plausibility": 0.25,
            "model_agreement": 0.20,
            "cross_source_consistency": 0.10,
        }
    )
    unavailable_component_score: float = 25.0
    automatic_alert_min_trust: float = 70.0
    review_below_trust: float = 70.0


@dataclass(frozen=True)
class PipelineConfig:
    feature: FeatureConfig = field(default_factory=FeatureConfig)
    anomaly: AnomalyConfig = field(default_factory=AnomalyConfig)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    model_id: str = "hydrolink-development"
    model_version: str = "1.0.0"
    random_seed: int = 42

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_CONFIG = PipelineConfig()

