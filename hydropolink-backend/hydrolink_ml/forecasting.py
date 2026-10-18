"""Time-series forecasting with baselines, boosted trees and lag-sequence regression."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import ForecastConfig
from .features import FEATURE_NAMES, FeatureRow


FORECAST_FEATURE_NAMES = tuple(name for name in FEATURE_NAMES if name not in {"missing_indicator"})
SEQUENCE_FEATURE_NAMES = ("value_m", "lag_1", "lag_3", "lag_6", "lag_24")


@dataclass(frozen=True)
class ForecastSample:
    station_id: str
    feature_row: FeatureRow
    target_timestamp: datetime
    target: float


@dataclass
class StationForecastModel:
    station_id: str
    algorithm: str
    model: object
    feature_names: tuple[str, ...]
    interval_half_width: float
    interval_coverage_target: float
    training_samples: int
    validation_metrics: dict[str, float]
    lower_physical_bound: float
    upper_data_bound: float


@dataclass
class ForecastBundle:
    station_models: dict[str, StationForecastModel]
    horizon_steps: int
    data_mode: str
    test_metrics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ForecastPrediction:
    predicted_value: float
    lower_bound: float
    upper_bound: float
    interval_coverage_target: float
    algorithm: str
    horizon_steps: int


class ColumnBaselineRegressor:
    """A serialisable forecast baseline that returns its single input column."""

    def fit(self, features: np.ndarray, targets: np.ndarray) -> "ColumnBaselineRegressor":
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        return np.asarray(features[:, 0], dtype=float)


def make_forecast_samples(rows: Iterable[FeatureRow], horizon_steps: int) -> list[ForecastSample]:
    grouped: dict[str, list[FeatureRow]] = {}
    for row in rows:
        grouped.setdefault(row.station_id, []).append(row)
    samples: list[ForecastSample] = []
    for station_id, station_rows in grouped.items():
        ordered = sorted(station_rows, key=lambda item: item.timestamp)
        for index in range(0, len(ordered) - horizon_steps):
            target_observation = ordered[index + horizon_steps].source_observation
            if target_observation.value_m is None or target_observation.fault_type != "normal":
                continue
            if ordered[index].source_observation.value_m is None:
                continue
            samples.append(
                ForecastSample(
                    station_id=station_id,
                    feature_row=ordered[index],
                    target_timestamp=ordered[index + horizon_steps].timestamp,
                    target=float(target_observation.value_m),
                )
            )
    return samples


def _matrix(samples: list[ForecastSample], names: tuple[str, ...]) -> np.ndarray:
    return np.vstack([sample.feature_row.as_array(names) for sample in samples])


def _metrics(targets: np.ndarray, predictions: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(targets, predictions)),
        "rmse": float(np.sqrt(mean_squared_error(targets, predictions))),
    }


def _candidate_models(seed: int) -> dict[str, tuple[object, tuple[str, ...]]]:
    return {
        "persistence": (ColumnBaselineRegressor(), ("value_m",)),
        "historical_average": (ColumnBaselineRegressor(), ("rolling_mean_6",)),
        "gradient_boosting": (
            GradientBoostingRegressor(
                n_estimators=180,
                learning_rate=0.035,
                max_depth=3,
                min_samples_leaf=8,
                loss="huber",
                random_state=seed,
            ),
            FORECAST_FEATURE_NAMES,
        ),
        "hist_gradient_boosting": (
            HistGradientBoostingRegressor(
                max_iter=180,
                learning_rate=0.045,
                max_leaf_nodes=15,
                l2_regularization=0.1,
                random_state=seed,
            ),
            FORECAST_FEATURE_NAMES,
        ),
        "ridge_lag_sequence": (
            Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=1.0))]),
            SEQUENCE_FEATURE_NAMES,
        ),
    }


def train_forecast_bundle(
    train_samples: Iterable[ForecastSample],
    validation_samples: Iterable[ForecastSample],
    config: ForecastConfig,
    data_mode: str,
) -> ForecastBundle:
    train_grouped: dict[str, list[ForecastSample]] = {}
    validation_grouped: dict[str, list[ForecastSample]] = {}
    for sample in train_samples:
        train_grouped.setdefault(sample.station_id, []).append(sample)
    for sample in validation_samples:
        validation_grouped.setdefault(sample.station_id, []).append(sample)
    station_models: dict[str, StationForecastModel] = {}
    for station_id, training in train_grouped.items():
        validation = validation_grouped.get(station_id, [])
        if len(training) < config.minimum_station_samples or len(validation) < 30:
            continue
        validation_targets = np.asarray([sample.target for sample in validation])
        candidate_metrics: dict[str, dict[str, float]] = {}
        fitted: dict[str, tuple[object, tuple[str, ...], np.ndarray]] = {}
        for name, (model, feature_names) in _candidate_models(config.random_seed).items():
            model.fit(_matrix(training, feature_names), np.asarray([sample.target for sample in training]))
            predictions = np.asarray(model.predict(_matrix(validation, feature_names)), dtype=float)
            candidate_metrics[name] = _metrics(validation_targets, predictions)
            fitted[name] = (model, feature_names, predictions)
        selected_name = min(fitted, key=lambda name: candidate_metrics[name]["mae"])
        selected_model, selected_features, validation_predictions = fitted[selected_name]
        residuals = np.abs(validation_targets - validation_predictions)
        half_width = float(np.quantile(residuals, config.interval_coverage))
        training_values = np.asarray([sample.target for sample in training])
        upper_bound = float(max(np.quantile(training_values, 0.999) * 1.5, np.max(training_values) * 1.1))
        station_models[station_id] = StationForecastModel(
            station_id=station_id,
            algorithm=selected_name,
            model=selected_model,
            feature_names=selected_features,
            interval_half_width=max(half_width, 1e-6),
            interval_coverage_target=config.interval_coverage,
            training_samples=len(training),
            validation_metrics={
                f"{name}_{metric}": value
                for name, metrics in candidate_metrics.items()
                for metric, value in metrics.items()
            },
            lower_physical_bound=0.0,
            upper_data_bound=upper_bound,
        )
    if not station_models:
        raise ValueError("no station has sufficient samples for forecasting")
    return ForecastBundle(
        station_models=station_models,
        horizon_steps=config.horizon_steps,
        data_mode=data_mode,
    )


def predict_forecast(bundle: ForecastBundle, row: FeatureRow) -> ForecastPrediction | None:
    station_model = bundle.station_models.get(row.station_id)
    if station_model is None:
        return None
    features = row.as_array(station_model.feature_names).reshape(1, -1)
    raw = float(station_model.model.predict(features)[0])
    prediction = min(station_model.upper_data_bound, max(station_model.lower_physical_bound, raw))
    lower = max(station_model.lower_physical_bound, prediction - station_model.interval_half_width)
    upper = min(station_model.upper_data_bound, prediction + station_model.interval_half_width)
    return ForecastPrediction(
        predicted_value=prediction,
        lower_bound=lower,
        upper_bound=upper,
        interval_coverage_target=station_model.interval_coverage_target,
        algorithm=station_model.algorithm,
        horizon_steps=bundle.horizon_steps,
    )


def evaluate_forecasts(bundle: ForecastBundle, samples: Iterable[ForecastSample]) -> dict[str, object]:
    grouped: dict[str, list[ForecastSample]] = {}
    for sample in samples:
        if sample.station_id in bundle.station_models:
            grouped.setdefault(sample.station_id, []).append(sample)
    station_metrics: dict[str, dict[str, object]] = {}
    all_targets: list[float] = []
    all_predictions: list[float] = []
    all_persistence: list[float] = []
    all_historical: list[float] = []
    covered = 0
    widths: list[float] = []
    for station_id, station_samples in grouped.items():
        targets = np.asarray([sample.target for sample in station_samples])
        predictions = [predict_forecast(bundle, sample.feature_row) for sample in station_samples]
        valid = [prediction for prediction in predictions if prediction is not None]
        predicted = np.asarray([prediction.predicted_value for prediction in valid])
        persistence = np.asarray([sample.feature_row.values["value_m"] for sample in station_samples])
        historical = np.asarray([sample.feature_row.values["rolling_mean_6"] for sample in station_samples])
        station_covered = sum(
            prediction.lower_bound <= target <= prediction.upper_bound
            for target, prediction in zip(targets, valid, strict=True)
        )
        station_widths = [prediction.upper_bound - prediction.lower_bound for prediction in valid]
        metrics = _metrics(targets, predicted)
        metrics.update(
            {
                "persistence_mae": float(mean_absolute_error(targets, persistence)),
                "persistence_rmse": float(np.sqrt(mean_squared_error(targets, persistence))),
                "historical_average_mae": float(mean_absolute_error(targets, historical)),
                "historical_average_rmse": float(np.sqrt(mean_squared_error(targets, historical))),
                "interval_coverage": station_covered / max(1, len(targets)),
                "mean_interval_width": float(np.mean(station_widths)),
                "samples": len(targets),
                "selected_algorithm": bundle.station_models[station_id].algorithm,
            }
        )
        station_metrics[station_id] = metrics
        all_targets.extend(targets.tolist())
        all_predictions.extend(predicted.tolist())
        all_persistence.extend(persistence.tolist())
        all_historical.extend(historical.tolist())
        covered += station_covered
        widths.extend(station_widths)
    if not all_targets:
        raise ValueError("no forecast samples can be evaluated")
    targets_array = np.asarray(all_targets)
    overall = _metrics(targets_array, np.asarray(all_predictions))
    overall.update(
        {
            "persistence_mae": float(mean_absolute_error(targets_array, np.asarray(all_persistence))),
            "persistence_rmse": float(np.sqrt(mean_squared_error(targets_array, np.asarray(all_persistence)))),
            "historical_average_mae": float(mean_absolute_error(targets_array, np.asarray(all_historical))),
            "historical_average_rmse": float(np.sqrt(mean_squared_error(targets_array, np.asarray(all_historical)))),
            "interval_coverage": covered / len(all_targets),
            "mean_interval_width": float(np.mean(widths)),
            "samples": len(all_targets),
            "by_station": station_metrics,
        }
    )
    return overall

