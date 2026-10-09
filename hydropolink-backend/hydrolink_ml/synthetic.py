"""Reproducible, clearly labelled development data and fault injection."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np

from .schema import Observation


DEVELOPMENT_STATIONS = {
    "C1H019": {"base": 0.92, "latitude": -26.95, "longitude": 29.29},
    "A2H049": {"base": 1.55, "latitude": -25.98, "longitude": 27.84},
    "LMP-CR-04": {"base": 2.35, "latitude": -24.80, "longitude": 28.90},
}

FAULT_TYPES = (
    "spike_up",
    "spike_down",
    "frozen",
    "missing",
    "stale_timestamp",
    "rapid_change",
    "invalid",
)


def generate_development_observations(
    periods: int = 3120,
    start: datetime | None = None,
    seed: int = 42,
) -> list[Observation]:
    """Create physically plausible hourly development series, never labelled as real data."""
    if periods < 300:
        raise ValueError("at least 300 periods are required for development training")
    # Fixed dates make the development benchmark reproducible.  They are close
    # to the 2026 prototype period but remain explicitly synthetic.
    start = start or datetime(2026, 6, 1, tzinfo=timezone.utc)
    rng = np.random.default_rng(seed)
    observations: list[Observation] = []
    for station_index, (station_id, metadata) in enumerate(DEVELOPMENT_STATIONS.items()):
        level = float(metadata["base"])
        rainfall_memory = 0.0
        for step in range(periods):
            timestamp = start + timedelta(hours=step)
            seasonal = 0.06 * np.sin(2 * np.pi * step / (24 * 30) + station_index)
            diurnal = 0.015 * np.sin(2 * np.pi * step / 24)
            rainfall = float(rng.gamma(1.4, 2.0)) if rng.random() < 0.055 else 0.0
            rainfall_memory = 0.82 * rainfall_memory + rainfall
            target = float(metadata["base"]) + seasonal + diurnal + 0.012 * rainfall_memory
            level = 0.93 * level + 0.07 * target + float(rng.normal(0.0, 0.008))
            observations.append(
                Observation(
                    station_id=station_id,
                    timestamp=timestamp,
                    received_at=timestamp + timedelta(minutes=5),
                    value_m=max(0.02, level),
                    rainfall_mm=rainfall,
                    latitude=float(metadata["latitude"]),
                    longitude=float(metadata["longitude"]),
                    source="synthetic_development_v1",
                    fault_type="normal",
                )
            )
    return observations


def chronological_split(
    observations: Iterable[Observation], train_fraction: float = 0.60, validation_fraction: float = 0.20
) -> tuple[list[Observation], list[Observation], list[Observation]]:
    if train_fraction <= 0 or validation_fraction <= 0 or train_fraction + validation_fraction >= 1:
        raise ValueError("invalid chronological split fractions")
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.station_id].append(observation)
    train: list[Observation] = []
    validation: list[Observation] = []
    test: list[Observation] = []
    for station_items in grouped.values():
        ordered = sorted(station_items, key=lambda item: item.timestamp)
        train_end = int(len(ordered) * train_fraction)
        validation_end = int(len(ordered) * (train_fraction + validation_fraction))
        train.extend(ordered[:train_end])
        validation.extend(ordered[train_end:validation_end])
        test.extend(ordered[validation_end:])
    return train, validation, test


def inject_faults(
    observations: Iterable[Observation],
    seed: int,
    fraction_per_category: float = 0.018,
) -> list[Observation]:
    """Inject independent labelled faults without changing the clean source series."""
    if not 0 < fraction_per_category < 0.1:
        raise ValueError("fraction_per_category must be between 0 and 0.1")
    rng = np.random.default_rng(seed)
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.station_id].append(observation)
    output: list[Observation] = []
    for station_items in grouped.values():
        series = sorted(station_items, key=lambda item: item.timestamp)
        count = max(1, int(len(series) * fraction_per_category))
        eligible = np.arange(30, max(31, len(series) - 12))
        needed = count * len(FAULT_TYPES)
        if len(eligible) < needed:
            raise ValueError("not enough observations for independent fault injection")
        selected = rng.choice(eligible, size=needed, replace=False)
        by_fault = {
            fault: sorted(int(index) for index in selected[pos * count : (pos + 1) * count])
            for pos, fault in enumerate(FAULT_TYPES)
        }
        mutated = list(series)
        for fault, indices in by_fault.items():
            for index in indices:
                original = mutated[index]
                prior = mutated[index - 1]
                baseline = original.value_m or prior.value_m or 1.0
                if fault == "spike_up":
                    replacement = original.with_updates(value_m=baseline + max(0.8, baseline * 1.4), fault_type=fault)
                elif fault == "spike_down":
                    replacement = original.with_updates(value_m=max(0.0, baseline - max(0.7, baseline * 0.8)), fault_type=fault)
                elif fault == "frozen":
                    replacement = original.with_updates(value_m=prior.value_m, fault_type=fault)
                    for offset in range(1, min(8, len(mutated) - index)):
                        mutated[index + offset] = mutated[index + offset].with_updates(
                            value_m=prior.value_m, fault_type=fault
                        )
                elif fault == "missing":
                    replacement = original.with_updates(value_m=None, fault_type=fault)
                elif fault == "stale_timestamp":
                    replacement = original.with_updates(
                        received_at=original.timestamp + timedelta(hours=12), fault_type=fault
                    )
                elif fault == "rapid_change":
                    replacement = original.with_updates(value_m=baseline + 0.55, fault_type=fault)
                elif fault == "invalid":
                    replacement = original.with_updates(value_m=-1.0, fault_type=fault)
                else:
                    raise AssertionError(f"unsupported fault: {fault}")
                mutated[index] = replacement
        output.extend(mutated)
    return sorted(output, key=lambda item: (item.station_id, item.timestamp))

