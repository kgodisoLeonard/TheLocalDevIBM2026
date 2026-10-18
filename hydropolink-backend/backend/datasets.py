"""
Builds the training set from every source, best first, and records where
each station's data came from. Used by the notebook.

Per station (series key = "<station>:<signal>", signal = flow | stage):
  1. real gauge history: GRDC file (matched by coordinates) or DWS Verified (opt-in)
  2. GloFAS modelled discharge (labelled "modelled", not gauge truth)
  3. the API's own logged readings (shared/readings.csv), once there are enough days
Plus: unmatched GRDC files train as their own stations (any real gauge
history teaches the shared models what normal behaviour looks like).
Aux per day: [log(gauge) - log(GloFAS)] when both exist, and 3-day rainfall.
"""
from __future__ import annotations

import csv
import os
from datetime import date, timedelta
from typing import Dict, Tuple

import numpy as np

from . import features as F
from . import sources as S

MIN_DAYS = 200


def signal_for(station_id: str, flow_cap) -> str:
    """Rivers are scored on flow (m3/s) when DWS reports it, so live readings
    share units with GRDC/GloFAS history. Dams/others use stage (m)."""
    return "flow" if F.station_kind(station_id) == "river" and flow_cap is not None else "stage"


def series_key(station_id: str, signal: str) -> str:
    return f"{station_id}:{signal}"


def load_logged_readings(path=None) -> Dict[str, Dict[str, float]]:
    path = path or os.path.join(S.SHARED_DIR, "readings.csv")
    out: Dict[str, list] = {}
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                fc = float(r["flow_cap"]) if r.get("flow_cap") not in (None, "") else None
                if F.parse_ts(r["timestamp"]) is None:
                    continue   # offline placeholder rows are not real observations
                sig = signal_for(r["station_id"], fc)
                v = fc if sig == "flow" else float(r["stage"])
                out.setdefault(series_key(r["station_id"], sig), []).append((r["timestamp"], v))
            except (KeyError, ValueError):
                continue
    return {k: dict(F.daily_last(v)) for k, v in out.items()}


def _aligned(values: Dict[str, float], glofas: Dict[str, float], rain: Dict[str, float],
             gauge_is_real: bool) -> Tuple[np.ndarray, np.ndarray, list]:
    days = sorted(values)
    v = np.array([values[d] for d in days], dtype=float)
    aux = np.full((len(days), 2), np.nan)
    for i, d in enumerate(days):
        if gauge_is_real:
            aux[i, 0] = F.log_disagreement(values[d], glofas.get(d))
        r3 = S.rain_3day(rain, d) if rain else None
        if r3 is not None:
            aux[i, 1] = r3
    return v, aux, days


def build_training_set(start: str = "2016-01-01", end: str | None = None,
                       use_dws_verified: bool = False, verbose: bool = True):
    end = end or (date.today() - timedelta(days=6)).isoformat()   # ERA5 lag
    stations = S.load_stations()
    grdc = S.load_grdc_dir()
    logged = load_logged_readings()
    series, aux, report = {}, {}, {}

    def add(key, values, glofas, rain, source, real):
        if len(values) < MIN_DAYS:
            return False
        v, a, days = _aligned(values, glofas, rain, real)
        series[key], aux[key] = v, a
        report[key] = {"source": source, "real_gauge": real, "days": len(days),
                       "from": days[0], "to": days[-1],
                       "with_glofas_check": int(np.isfinite(a[:, 0]).sum()),
                       "with_rain": int(np.isfinite(a[:, 1]).sum())}
        return True

    # GRDC files matched to a registry station by coordinates.
    grdc_by_station = {}
    for gid, (meta, vals) in grdc.items():
        sid = S.match_grdc_to_station(meta, stations)
        grdc_by_station.setdefault(sid or gid, (meta, vals))

    # 1-2: registry stations with coordinates.
    for sid, st in stations.items():
        lat, lon = st["lat"], st["lon"]
        rain = S.rain_history(lat, lon, start, end)
        if F.station_kind(sid) == "dam":
            continue   # GloFAS is river discharge; dams train on logged/synthetic stage
        glofas = S.glofas_history(lat, lon, start, end)
        key = series_key(sid, "flow")
        if sid in grdc_by_station and add(key, grdc_by_station[sid][1], glofas, rain, "GRDC gauge", True):
            continue
        if use_dws_verified:
            dws = S.dws_verified_daily(sid, start, end)
            if add(key, dws, glofas, rain, "DWS Verified gauge", True):
                continue
        add(key, glofas, glofas, rain, "GloFAS modelled", False)

    # Unmatched GRDC stations train as themselves.
    for gid, (meta, vals) in grdc_by_station.items():
        if not gid.startswith("GRDC") or "lat" not in meta:
            continue
        glofas = S.glofas_history(meta["lat"], meta["lon"], start, end)
        rain = S.rain_history(meta["lat"], meta["lon"], start, end)
        add(series_key(gid, "flow"), vals, glofas, rain, "GRDC gauge (unmatched)", True)

    # 3: the API's own logged readings, for keys not already covered.
    for key, vals in logged.items():
        if key not in series:
            add(key, vals, {}, {}, "DWS live log", True)

    if verbose:
        for k, r in sorted(report.items()):
            print(f"{k:18s} {r['source']:24s} {r['days']:5d} days {r['from']}..{r['to']} "
                  f"glofas-check {r['with_glofas_check']:5d} rain {r['with_rain']:5d}")
        print(f"registry stations with coords: {len(stations)} | GRDC files: {len(grdc)} | "
              f"logged keys: {len(logged)}")
    return series, aux, report
