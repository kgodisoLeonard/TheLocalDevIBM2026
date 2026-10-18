"""
HydroLink feature engineering — the ONE place features are defined.

Imported by BOTH the Jupyter training notebook and the FastAPI service, so
training and serving can never drift apart. If you change anything here,
bump FEATURE_VERSION; the API refuses bundles built with a different version.

Pure numpy, no pandas, so the API container stays light.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

FEATURE_VERSION = "hl-feat-3"

# Inputs to the anomaly model (Model A), in order.
ANOMALY_FEATURES = ["z_level", "step_rate", "flatline", "forecast_residual",
                    "model_disagreement", "rain_context"]
# model_disagreement: gauge flow vs GloFAS modelled flow (log space, per-station
#                     normalised). 0 when either side is missing.
# rain_context:       log1p(3-day rainfall mm). Lets the forest learn that a
#                     sharp rise is normal after rain and suspicious without it.
# Inputs to the forecaster (Model B), in order. Lags are in robust-z units.
FORECAST_FEATURES = ["lag1", "lag2", "lag3", "lag1_minus_lag2"]
N_LAGS = 3
MIN_HISTORY_FOR_STATS = 8


def station_kind(station_id: str) -> str:
    """DWS codes: 3rd char 'H' = river gauge, 'R' = reservoir/dam."""
    c = station_id[2:3].upper()
    return {"H": "river", "R": "dam"}.get(c, "other")


@dataclass
class StationStats:
    median: float
    mad: float          # robust spread (scaled MAD), floored
    step_scale: float   # typical |change| between readings, floored
    n: int
    disagree_median: float = 0.0  # typical log(gauge) - log(GloFAS) bias
    disagree_scale: float = 1.0   # its robust spread

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


def compute_station_stats(stages: Sequence[float],
                          disagree_raw: Optional[Sequence[float]] = None) -> StationStats:
    s = np.asarray(stages, dtype=float)
    med = float(np.median(s))
    mad = float(1.4826 * np.median(np.abs(s - med)))
    steps = np.abs(np.diff(s)) if len(s) > 1 else np.array([0.0])
    step = float(np.median(steps))
    # Floors stop a perfectly calm station from producing infinite z-scores.
    floor = max(0.01, 0.01 * abs(med))
    dm, ds = 0.0, 1.0
    if disagree_raw is not None:
        d = np.asarray(disagree_raw, dtype=float)
        d = d[np.isfinite(d)]
        if len(d) >= 30:   # GloFAS has a station-specific bias; learn it
            dm = float(np.median(d))
            ds = max(float(1.4826 * np.median(np.abs(d - dm))), 0.05)
    return StationStats(median=med, mad=max(mad, floor), step_scale=max(step, floor / 2),
                        n=int(len(s)), disagree_median=dm, disagree_scale=ds)


def log_disagreement(observed: Optional[float], modelled: Optional[float]) -> float:
    """Raw log-space gap between a gauge's flow and GloFAS; NaN if unknown."""
    if observed is None or modelled is None or observed < 0 or modelled < 0:
        return float("nan")
    return float(np.log1p(observed) - np.log1p(modelled))


def provisional_stats(stage: float) -> StationStats:
    """For a station we have never seen: neutral stats (z=0), flagged by n=0."""
    floor = max(0.02, 0.05 * abs(stage))
    return StationStats(median=float(stage), mad=floor, step_scale=floor / 2, n=0)


def station_kind_noisy(st: "StationStats") -> bool:
    """A gauge whose readings normally move between samples. Very calm series
    (e.g. a dam reported to 1 cm) legitimately repeat, so the stuck rule is off."""
    return st.step_scale > max(0.0005, 0.0002 * abs(st.median))


def _z(x: float, st: StationStats) -> float:
    return (x - st.median) / st.mad


def forecast_row(prev_stages: Sequence[float], st: StationStats) -> np.ndarray:
    """Features to predict the NEXT reading from the last N_LAGS readings
    (most recent last). Missing lags are padded with the median (z=0)."""
    prev = list(prev_stages)[-N_LAGS:]
    lags = [_z(v, st) for v in reversed(prev)]          # lag1 = most recent
    while len(lags) < N_LAGS:
        lags.append(lags[-1] if lags else 0.0)
    return np.array([lags[0], lags[1], lags[2], lags[0] - lags[1]], dtype=float)


def anomaly_row(stage: float, prev_stages: Sequence[float], st: StationStats,
                forecast_stage: Optional[float], disagree_raw: float = float("nan"),
                rain_3d_mm: Optional[float] = None) -> np.ndarray:
    prev = list(prev_stages)
    z_level = _z(stage, st)
    step_rate = (stage - prev[-1]) / st.step_scale if prev else 0.0
    # Stuck-sensor signal: how many previous readings are exactly identical.
    flat = 0
    for v in reversed(prev):
        if abs(v - stage) < 1e-9:
            flat += 1
        else:
            break
    flatline = min(flat, 24) / 24.0
    resid = (stage - forecast_stage) / st.step_scale if forecast_stage is not None else 0.0
    disagree = ((disagree_raw - st.disagree_median) / st.disagree_scale
                if np.isfinite(disagree_raw) else 0.0)
    rain = float(np.log1p(max(rain_3d_mm, 0.0))) if rain_3d_mm is not None else 0.0
    # Clip so a single absurd value can't dominate the forest's split range.
    return np.clip(np.array([z_level, step_rate, flatline, resid, disagree, rain], dtype=float), -50, 50)


def series_to_training_rows(stages: Sequence[float], st: StationStats
                            ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """From one station's ordered series build:
       Xf (forecast features), yf (next value in z units), idx (row -> position)."""
    Xf, yf, idx = [], [], []
    for t in range(N_LAGS, len(stages)):
        Xf.append(forecast_row(stages[t - N_LAGS:t], st))
        yf.append(_z(stages[t], st))
        idx.append(t)
    return np.array(Xf), np.array(yf), np.array(idx)


def z_to_stage(zv: float, st: StationStats) -> float:
    return zv * st.mad + st.median


# ---------------------------------------------------------------------------
# Synthetic data — used ONLY (a) as a labelled bootstrap when real history is
# too short, and (b) to inject known faults for evaluation. Always reported
# in the manifest's data_sources so nobody mistakes it for real telemetry.
# ---------------------------------------------------------------------------
def synthetic_series(base: float, n: int, rng: np.random.Generator,
                     kind: str = "river") -> np.ndarray:
    t = np.arange(n)
    diurnal = 0.03 * base * np.sin(2 * np.pi * t / 24)
    walk = np.cumsum(rng.normal(0, 0.004 * base, n))
    walk -= np.linspace(0, walk[-1], n)       # keep it mean-reverting
    noise = rng.normal(0, 0.003 * base, n)
    s = base + diurnal + walk + noise
    if kind == "river":                        # occasional rain pulses
        for start in rng.choice(n, size=max(1, n // 300), replace=False):
            pulse = 0.25 * base * np.exp(-np.arange(n - start) / 12.0)
            s[start:] += pulse * (1 - np.exp(-np.arange(n - start) / 2.0))
    return np.maximum(s, 0.0)


FAULT_TYPES = ("spike", "flatline", "drift", "dropout")


def inject_faults(stages: np.ndarray, rng: np.random.Generator, rate: float = 0.04
                  ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Return (corrupted series, boolean fault mask, fault type per index)."""
    s = stages.copy()
    mask = np.zeros(len(s), dtype=bool)
    kinds = [""] * len(s)
    scale = max(float(np.std(stages)), 0.02)
    t = N_LAGS + 1
    while t < len(s) - 6:
        if rng.random() < rate:
            f = rng.choice(FAULT_TYPES)
            if f == "spike":
                s[t] += rng.choice([-1, 1]) * rng.uniform(4, 10) * scale
                span = [t]
            elif f == "flatline":
                L = int(rng.integers(4, 7))
                s[t:t + L] = s[t - 1]
                span = list(range(t + 2, t + L))   # first repeats look normal
            elif f == "drift":
                L = int(rng.integers(4, 7))
                s[t:t + L] += np.linspace(1, 5, L) * scale
                span = list(range(t + 1, t + L))
            else:  # dropout: sensor reports ~0
                s[t] = 0.0
                span = [t]
            for i in span:
                mask[i] = True
                kinds[i] = f
            t += 10
        t += 1
    return s, mask, kinds


def daily_last(points: Sequence[Tuple[str, float]]) -> List[Tuple[str, float]]:
    """Resample (timestamp, value) to one value per day (the day's last reading).
    Models are trained on daily data; live DWS readings are roughly hourly."""
    out: Dict[str, float] = {}
    for ts, v in points:
        d = parse_ts(ts)
        out[(d.date().isoformat() if d else ts)] = v
    return sorted(out.items())


def parse_ts(ts: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def hours_between(a: datetime, b: datetime) -> float:
    return abs((a - b) / timedelta(hours=1))
