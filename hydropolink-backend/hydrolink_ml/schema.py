"""Canonical observation schema and CSV serialisation helpers."""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


CANONICAL_COLUMNS = (
    "station_id",
    "timestamp",
    "received_at",
    "value_m",
    "reading_type",
    "unit",
    "source",
    "latitude",
    "longitude",
    "rainfall_mm",
    "is_imputed",
    "fault_type",
)


def parse_timestamp(value: str | datetime) -> datetime:
    """Parse an ISO-like timestamp and always return timezone-aware UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if not text:
            raise ValueError("timestamp is empty")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = None
        for candidate in (text, text.replace("/", "-")):
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except ValueError:
                pass
        if parsed is None:
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%m-%Y %H:%M"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    pass
        if parsed is None:
            raise ValueError(f"invalid timestamp: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return result


@dataclass(frozen=True)
class Observation:
    station_id: str
    timestamp: datetime
    value_m: float | None
    source: str
    received_at: datetime | None = None
    reading_type: str = "stage"
    unit: str = "m"
    latitude: float | None = None
    longitude: float | None = None
    rainfall_mm: float | None = None
    is_imputed: bool = False
    fault_type: str = "normal"

    def __post_init__(self) -> None:
        station = self.station_id.strip().upper()
        if not station:
            raise ValueError("station_id is required")
        if self.unit != "m":
            raise ValueError("canonical water-level observations must use metres")
        object.__setattr__(self, "station_id", station)
        object.__setattr__(self, "timestamp", parse_timestamp(self.timestamp))
        received = self.received_at or self.timestamp
        object.__setattr__(self, "received_at", parse_timestamp(received))
        if self.value_m is not None and not math.isfinite(float(self.value_m)):
            object.__setattr__(self, "value_m", None)

    @classmethod
    def from_mapping(cls, row: dict[str, object], source_default: str = "csv_import") -> "Observation":
        value = row.get("value_m", row.get("stage", row.get("value")))
        timestamp = row.get("timestamp", row.get("date_time", row.get("date")))
        station_id = row.get("station_id", row.get("station", row.get("station_code")))
        if timestamp is None or station_id is None:
            raise ValueError("station_id and timestamp columns are required")
        received_raw = row.get("received_at") or timestamp
        return cls(
            station_id=str(station_id),
            timestamp=parse_timestamp(str(timestamp)),
            received_at=parse_timestamp(str(received_raw)),
            value_m=_optional_float(value),
            source=str(row.get("source") or source_default),
            reading_type=str(row.get("reading_type") or "stage"),
            unit=str(row.get("unit") or "m"),
            latitude=_optional_float(row.get("latitude")),
            longitude=_optional_float(row.get("longitude")),
            rainfall_mm=_optional_float(row.get("rainfall_mm")),
            is_imputed=str(row.get("is_imputed", "false")).lower() in {"1", "true", "yes"},
            fault_type=str(row.get("fault_type") or "normal"),
        )

    def with_updates(self, **changes: object) -> "Observation":
        return replace(self, **changes)

    def to_row(self) -> dict[str, object]:
        row = asdict(self)
        row["timestamp"] = self.timestamp.isoformat()
        row["received_at"] = self.received_at.isoformat() if self.received_at else ""
        row["is_imputed"] = str(self.is_imputed).lower()
        return row


def deduplicate_observations(observations: Iterable[Observation]) -> list[Observation]:
    """Keep the last received record for each station/timestamp pair."""
    latest: dict[tuple[str, datetime], Observation] = {}
    for observation in observations:
        key = (observation.station_id, observation.timestamp)
        current = latest.get(key)
        if current is None or (observation.received_at or observation.timestamp) >= (
            current.received_at or current.timestamp
        ):
            latest[key] = observation
    return sorted(latest.values(), key=lambda item: (item.station_id, item.timestamp))


def read_observations_csv(path: Path, source_default: str = "csv_import") -> list[Observation]:
    observations: list[Observation] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for line_number, row in enumerate(csv.DictReader(stream), start=2):
            try:
                observations.append(Observation.from_mapping(row, source_default=source_default))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return deduplicate_observations(observations)


def write_observations_csv(path: Path, observations: Iterable[Observation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        for observation in observations:
            writer.writerow(observation.to_row())

