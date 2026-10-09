from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from hydrolink_ml.alerting import decide_alert
from hydrolink_ml.anomaly import AnomalyPrediction, evaluate_anomaly_rows, predict_anomaly, train_anomaly_bundle
from hydrolink_ml.artifacts import load_artifacts, save_artifacts
from hydrolink_ml.config import AnomalyConfig, FeatureConfig, ForecastConfig, PipelineConfig, TrustConfig
from hydrolink_ml.features import build_feature_rows
from hydrolink_ml.forecasting import evaluate_forecasts, make_forecast_samples, predict_forecast, train_forecast_bundle
from hydrolink_ml.synthetic import chronological_split, generate_development_observations, inject_faults
from hydrolink_ml.trust import calculate_trust_score


class ModelAndTrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = PipelineConfig(
            feature=FeatureConfig(minimum_history=24),
            anomaly=AnomalyConfig(minimum_station_samples=50, random_seed=21),
            forecast=ForecastConfig(horizon_steps=6, minimum_station_samples=50, random_seed=21),
            trust=TrustConfig(),
            random_seed=21,
        )
        clean = generate_development_observations(periods=620, seed=21)
        cls.train, cls.validation_clean, cls.test_clean = chronological_split(clean)
        cls.validation_faulty = inject_faults(cls.validation_clean, seed=121)
        cls.test_faulty = inject_faults(cls.test_clean, seed=221)
        cls.train_rows = build_feature_rows(cls.train, cls.config.feature)
        cls.validation_rows = build_feature_rows(cls.validation_faulty, cls.config.feature)
        cls.test_rows = build_feature_rows(cls.test_faulty, cls.config.feature)
        cls.anomaly = train_anomaly_bundle(
            cls.train_rows, cls.validation_rows, cls.config.anomaly, "synthetic_test"
        )
        train_samples = make_forecast_samples(cls.train_rows, cls.config.forecast.horizon_steps)
        validation_clean_rows = build_feature_rows(cls.validation_clean, cls.config.feature)
        test_clean_rows = build_feature_rows(cls.test_clean, cls.config.feature)
        validation_samples = make_forecast_samples(validation_clean_rows, cls.config.forecast.horizon_steps)
        cls.test_samples = make_forecast_samples(test_clean_rows, cls.config.forecast.horizon_steps)
        cls.forecast = train_forecast_bundle(
            train_samples, validation_samples, cls.config.forecast, "synthetic_test"
        )

    def test_anomaly_training_and_held_out_evaluation(self) -> None:
        metrics = evaluate_anomaly_rows(self.anomaly, self.test_rows)
        self.assertIn("precision", metrics)
        self.assertIn("missing", metrics["by_fault"])
        self.assertGreater(metrics["samples"], 0)

    def test_missing_stale_frozen_spike_and_invalid_are_explained(self) -> None:
        expected = {
            "missing": "missing_observation",
            "stale_timestamp": "stale_timestamp",
            "frozen": "frozen_sensor",
            "invalid": "out_of_range",
        }
        for fault, reason in expected.items():
            matching = [row for row in self.test_rows if row.source_observation.fault_type == fault]
            self.assertTrue(matching, fault)
            self.assertTrue(any(reason in predict_anomaly(self.anomaly, row).reasons for row in matching), fault)
        spikes = [row for row in self.test_rows if row.source_observation.fault_type in {"spike_up", "spike_down"}]
        self.assertTrue(any(predict_anomaly(self.anomaly, row).is_anomaly for row in spikes))

    def test_forecasts_and_prediction_intervals_are_valid(self) -> None:
        metrics = evaluate_forecasts(self.forecast, self.test_samples)
        self.assertGreater(metrics["samples"], 0)
        self.assertGreaterEqual(metrics["interval_coverage"], 0.0)
        self.assertLessEqual(metrics["interval_coverage"], 1.0)
        prediction = predict_forecast(self.forecast, self.test_samples[0].feature_row)
        self.assertIsNotNone(prediction)
        self.assertLessEqual(prediction.lower_bound, prediction.predicted_value)
        self.assertGreaterEqual(prediction.upper_bound, prediction.predicted_value)

    def test_insufficient_station_history_has_no_forecast(self) -> None:
        unknown = replace(self.test_samples[0].feature_row, station_id="UNKNOWN")
        self.assertIsNone(predict_forecast(self.forecast, unknown))

    def test_artifact_round_trip_and_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "trusted-artifacts"
            save_artifacts(
                target,
                self.anomaly,
                self.forecast,
                {"model_id": "test", "model_version": "1"},
                [],
            )
            loaded = load_artifacts(target)
            self.assertEqual(loaded.metadata["model_id"], "test")
            with (target / "anomaly.joblib").open("ab") as stream:
                stream.write(b"tamper")
            with self.assertRaises(ValueError):
                load_artifacts(target)

    def test_trust_components_penalise_missing_and_unavailable_evidence(self) -> None:
        row = next(row for row in self.test_rows if row.source_observation.fault_type == "normal")
        normal_anomaly = AnomalyPrediction(False, (), 0.1, "station")
        forecast = predict_forecast(self.forecast, row)
        healthy = calculate_trust_score(
            row.source_observation,
            normal_anomaly,
            forecast,
            self.config.trust,
            as_of=row.received_at,
            cross_source_value=row.source_observation.value_m,
        )
        missing_observation = row.source_observation.with_updates(value_m=None)
        missing = calculate_trust_score(
            missing_observation,
            AnomalyPrediction(True, ("missing_observation",), None, "station"),
            None,
            self.config.trust,
            as_of=row.received_at,
        )
        self.assertEqual(set(healthy.components), set(self.config.trust.weights))
        self.assertLess(missing.final_score, healthy.final_score)
        self.assertFalse(missing.components["cross_source_consistency"].available)

    def test_alerts_do_not_confuse_quality_with_flood_risk(self) -> None:
        row = next(row for row in self.test_rows if row.source_observation.fault_type == "normal")
        anomaly = AnomalyPrediction(False, (), 0.1, "station")
        forecast = predict_forecast(self.forecast, row)
        trust = calculate_trust_score(
            row.source_observation,
            anomaly,
            forecast,
            self.config.trust,
            as_of=row.received_at,
            cross_source_value=row.source_observation.value_m,
        )
        decision = decide_alert(
            trust,
            anomaly,
            forecast,
            self.config.trust,
            elevated_reference_m=0.0,
            authoritative_flood_threshold_m=None,
        )
        self.assertEqual(decision.risk_level, "caution")
        self.assertFalse(decision.automatic_public_warning)
        self.assertTrue(decision.requires_human_review)


if __name__ == "__main__":
    unittest.main()

