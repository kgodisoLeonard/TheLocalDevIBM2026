from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hydrolink_ml.config import FeatureConfig
from hydrolink_ml.features import build_feature_rows
from hydrolink_ml.ingestion import import_historical_csv
from hydrolink_ml.schema import Observation, deduplicate_observations, parse_timestamp, read_observations_csv
from hydrolink_ml.synthetic import generate_development_observations, inject_faults


class SchemaAndFeatureTests(unittest.TestCase):
    def test_timestamp_is_utc_and_invalid_timestamp_fails(self) -> None:
        self.assertEqual(parse_timestamp("2026-01-01T02:00:00+02:00").hour, 0)
        with self.assertRaises(ValueError):
            parse_timestamp("not-a-date")

    def test_duplicate_keeps_latest_received_record(self) -> None:
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        earlier = Observation("A1H001", timestamp, 1.0, "first", received_at=timestamp)
        later = Observation("A1H001", timestamp, 1.2, "second", received_at=timestamp + timedelta(minutes=5))
        result = deduplicate_observations([later, earlier])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].value_m, 1.2)
        self.assertEqual(result[0].source, "second")

    def test_rolling_features_exclude_current_value(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        observations = [
            Observation("A1H001", start + timedelta(hours=index), 1.0, "test")
            for index in range(24)
        ]
        observations.append(Observation("A1H001", start + timedelta(hours=24), 10.0, "test"))
        rows = build_feature_rows(observations, FeatureConfig(minimum_history=24))
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].values["rolling_mean_6"], 1.0)
        self.assertEqual(rows[0].values["value_m"], 10.0)

    def test_future_change_does_not_change_past_features(self) -> None:
        observations = generate_development_observations(periods=320, seed=9)
        station = [item for item in observations if item.station_id == "C1H019"]
        config = FeatureConfig(minimum_history=24)
        before = build_feature_rows(station, config)
        modified = list(station)
        modified[-1] = modified[-1].with_updates(value_m=999.0)
        after = build_feature_rows(modified, config)
        self.assertEqual(before[-2].values, after[-2].values)

    def test_fault_injection_is_reproducible_and_preserves_labels(self) -> None:
        clean = generate_development_observations(periods=400, seed=12)
        first = inject_faults(clean, seed=77)
        second = inject_faults(clean, seed=77)
        self.assertEqual([item.to_row() for item in first], [item.to_row() for item in second])
        labels = {item.fault_type for item in first}
        self.assertTrue({"missing", "frozen", "spike_up", "invalid"}.issubset(labels))

    def test_csv_import_preserves_missing_values_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            output = Path(directory) / "canonical.csv"
            source.write_text(
                "Station,When,Level\nA1H001,2026-01-01T00:00:00Z,1.2\nA1H001,2026-01-01T01:00:00Z,\n",
                encoding="utf-8",
            )
            report = import_historical_csv(
                source,
                output,
                source_name="test authentic source",
                station_column="Station",
                timestamp_column="When",
                value_column="Level",
            )
            imported = read_observations_csv(output)
            self.assertEqual(report["accepted_rows"], 2)
            self.assertIsNone(imported[1].value_m)
            self.assertEqual(imported[0].source, "test authentic source")


if __name__ == "__main__":
    unittest.main()

