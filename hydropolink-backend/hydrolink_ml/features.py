"""Causal time-series features shared by training and inference."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable

import numpy as np

from .config import FeatureConfig
from .schema import Observation


FEATURE_NAMES = (
    "value_m",
    "lag_1",
    "lag_3",
    "lag_6",
    "lag_24",
    "rolling_mean_6",
    "rolling_std_6",
    "rolling_median_6",
    "rolling_min_24",
    "rolling_max_24",
    "diff_1",
    "rate_per_hour",
    "pct_change",
    "deviation_z_24",
    "robust_deviation_24",
    "elapsed_hours",
    "missing_indicator",
    "repeated_duration_hours",
    "hour_sin",
    "hour_cos",
    "day_of_year_sin",
    "day_of_year_cos",
    "rainfall_mm",
    "rainfall_rolling_6",
)


@dataclass(frozen=True)
class FeatureRow:
    station_id: str
    timestamp: datetime
    received_at: datetime
    values: dict[str, float]
    source_observation: Observation

    def as_array(self, names: Iterable[str] = FEATURE_NAMES) -> np.ndarray:
        return np.asarray([self.values[name] for name in names], dtype=float)


def _finite(values: Iterable[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def _safe_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(np.std(values, ddof=1))


def _lag_value(history: list[Observation], steps: int) -> float | None:
    if len(history) < steps:
        return None
    return history[-steps].value_m


def _last_observed(history: list[Observation]) -> Observation | None:
    return next((item for item in reversed(history) if item.value_m is not None), None)


def _repeat_duration(history: list[Observation], current: Observation) -> float:
    if current.value_m is None:
        return 0.0
    start = current.timestamp
    for item in reversed(history):
        if item.value_m is None or not math.isclose(item.value_m, current.value_m, rel_tol=0.0, abs_tol=1e-9):
            break
        start = item.timestamp
    return max(0.0, (current.timestamp - start).total_seconds() / 3600.0)


def build_feature_rows(
    observations: Iterable[Observation], config: FeatureConfig
) -> list[FeatureRow]:
    """Build causal features; rolling statistics exclude the current reading."""
    grouped: dict[str, list[Observation]] = {}
    for observation in observations:
        grouped.setdefault(observation.station_id, []).append(observation)

    rows: list[FeatureRow] = []
    for station_id, station_observations in grouped.items():
        ordered = sorted(station_observations, key=lambda item: item.timestamp)
        history: list[Observation] = []
        for current in ordered:
            prior_values = _finite(item.value_m for item in history)
            short = _finite(item.value_m for item in history[-config.short_window :])
            long = _finite(item.value_m for item in history[-config.long_window :])
            prior_rain = _finite(item.rainfall_mm for item in history[-config.short_window :])
            previous = _last_observed(history)
            lag_default = float(short[-1] if short else current.value_m or 0.0)
            rolling_mean = float(np.mean(short)) if short else lag_default
            rolling_std = _safe_std(short)
            rolling_med = float(median(short)) if short else lag_default
            long_mean = float(np.mean(long)) if long else rolling_mean
            long_std = _safe_std(long)
            long_med = float(median(long)) if long else rolling_med
            deviations = [abs(value - long_med) for value in long]
            mad = float(median(deviations)) if deviations else 0.0
            current_value = float(current.value_m) if current.value_m is not None else rolling_mean
            elapsed = (
                (current.timestamp - previous.timestamp).total_seconds() / 3600.0
                if previous is not None
                else config.expected_interval_hours
            )
            diff = current_value - float(previous.value_m) if previous and previous.value_m is not None else 0.0
            rate = diff / elapsed if elapsed > 0 else 0.0
            pct = diff / abs(float(previous.value_m)) if previous and previous.value_m not in (None, 0) else 0.0
            hour_angle = 2.0 * math.pi * current.timestamp.hour / 24.0
            day_angle = 2.0 * math.pi * current.timestamp.timetuple().tm_yday / 366.0
            values = {
                "value_m": current_value,
                "lag_1": float(_lag_value(history, 1) or lag_default),
                "lag_3": float(_lag_value(history, 3) or lag_default),
                "lag_6": float(_lag_value(history, 6) or lag_default),
                "lag_24": float(_lag_value(history, 24) or lag_default),
                "rolling_mean_6": rolling_mean,
                "rolling_std_6": rolling_std,
                "rolling_median_6": rolling_med,
                "rolling_min_24": float(min(long)) if long else lag_default,
                "rolling_max_24": float(max(long)) if long else lag_default,
                "diff_1": diff,
                "rate_per_hour": rate,
                "pct_change": pct,
                "deviation_z_24": (current_value - long_mean) / long_std if long_std > 1e-9 else 0.0,
                "robust_deviation_24": 0.6745 * (current_value - long_med) / mad if mad > 1e-9 else 0.0,
                "elapsed_hours": elapsed,
                "missing_indicator": 1.0 if current.value_m is None else 0.0,
                "repeated_duration_hours": _repeat_duration(history, current),
                "hour_sin": math.sin(hour_angle),
                "hour_cos": math.cos(hour_angle),
                "day_of_year_sin": math.sin(day_angle),
                "day_of_year_cos": math.cos(day_angle),
                "rainfall_mm": float(current.rainfall_mm or 0.0),
                "rainfall_rolling_6": float(sum(prior_rain)),
            }
            if len(prior_values) >= config.minimum_history:
                rows.append(
                    FeatureRow(
                        station_id=station_id,
                        timestamp=current.timestamp,
                        received_at=current.received_at or current.timestamp,
                        values=values,
                        source_observation=current,
                    )
                )
            history.append(current)
    return rows


def feature_matrix(rows: Iterable[FeatureRow], names: Iterable[str] = FEATURE_NAMES) -> np.ndarray:
    selected = tuple(names)
    return np.vstack([row.as_array(selected) for row in rows])

