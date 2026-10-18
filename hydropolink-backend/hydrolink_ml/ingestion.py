"""Authentic CSV ingestion and provenance-preserving standardisation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .schema import Observation, deduplicate_observations, parse_timestamp, write_observations_csv


def import_historical_csv(
    input_path: Path,
    output_path: Path,
    source_name: str,
    station_column: str = "station_id",
    timestamp_column: str = "timestamp",
    value_column: str = "value_m",
    unit: str = "m",
    rainfall_column: str | None = None,
    latitude_column: str | None = None,
    longitude_column: str | None = None,
) -> dict[str, object]:
    """Standardise an explicitly mapped public or authorised CSV.

    Unit conversion is deliberately not guessed.  Callers must supply metres or
    convert their source before import.
    """
    if unit != "m":
        raise ValueError("only metre-based water-level imports are accepted; convert explicitly first")
    observations: list[Observation] = []
    rejected: list[dict[str, object]] = []
    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {station_column, timestamp_column, value_column}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing required source columns: {sorted(missing)}")
        for line_number, row in enumerate(reader, start=2):
            try:
                raw_value = row.get(value_column, "").strip()
                value = float(raw_value) if raw_value else None
                observations.append(
                    Observation(
                        station_id=row[station_column],
                        timestamp=parse_timestamp(row[timestamp_column]),
                        received_at=parse_timestamp(row[timestamp_column]),
                        value_m=value,
                        rainfall_mm=float(row[rainfall_column]) if rainfall_column and row.get(rainfall_column) else None,
                        latitude=float(row[latitude_column]) if latitude_column and row.get(latitude_column) else None,
                        longitude=float(row[longitude_column]) if longitude_column and row.get(longitude_column) else None,
                        source=source_name,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                rejected.append({"line": line_number, "reason": str(exc)})
    standardised = deduplicate_observations(observations)
    write_observations_csv(output_path, standardised)
    report = {
        "source": source_name,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "accepted_rows": len(standardised),
        "rejected_rows": len(rejected),
        "rejections": rejected[:100],
        "provenance_note": "Values were imported from the named source without imputation.",
    }
    output_path.with_suffix(output_path.suffix + ".provenance.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report

