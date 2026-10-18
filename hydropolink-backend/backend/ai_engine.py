"""
HydroLink AI engine: loads the notebook-trained bundle from the shared
volume, verifies it, hot-reloads it when the notebook publishes a new one,
keeps per-station reading history, and scores readings.

Shared volume layout (host /home/linux1/shared):
  hydrolink_models.joblib          <- written by Jupyter
  hydrolink_models.manifest.json   <- written by Jupyter (commit point)
  readings.csv                     <- written by the API, read by Jupyter
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from . import datasets as D
from . import features as F
from . import sources as S
from . import training as T

SHARED_DIR = os.getenv("HYDROLINK_SHARED_DIR", "/shared")
MODEL_KEY = os.getenv("HYDROLINK_MODEL_KEY")          # same value in both containers
ALLOW_VERSION_SKEW = os.getenv("HYDROLINK_ALLOW_VERSION_SKEW") == "1"
STALE_HOURS = float(os.getenv("HYDROLINK_STALE_HOURS", "6"))
REVIEW_BELOW = int(os.getenv("HYDROLINK_REVIEW_BELOW", str(T.REVIEW_BELOW)))
RELOAD_CHECK_SECONDS = 5.0


class ModelRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bundle: Optional[dict] = None
        self.manifest: Dict[str, Any] = {}
        self.source = "none"
        self.last_error: Optional[str] = None
        self._manifest_mtime = 0.0
        self._last_check = 0.0
        self._fallback: Optional[dict] = None

    # -- loading -----------------------------------------------------------
    def _paths(self) -> Tuple[str, str]:
        return (os.path.join(SHARED_DIR, T.BUNDLE_NAME),
                os.path.join(SHARED_DIR, T.MANIFEST_NAME))

    def _verify_and_load(self, bpath: str, mpath: str) -> Tuple[dict, dict]:
        import joblib
        manifest = json.load(open(mpath))
        data = open(bpath, "rb").read()
        # 1. Integrity BEFORE unpickling: joblib/pickle executes code on load,
        #    so an unverified file on a shared volume is an attack surface.
        if hashlib.sha256(data).hexdigest() != manifest.get("sha256"):
            raise ValueError("sha256 mismatch: bundle changed after manifest was written")
        if MODEL_KEY:
            expected = hmac.new(MODEL_KEY.encode(), data, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, manifest.get("hmac_sha256") or ""):
                raise ValueError("HMAC signature invalid: bundle not signed with HYDROLINK_MODEL_KEY")
        # 2. Contract checks.
        if manifest.get("feature_version") != F.FEATURE_VERSION:
            raise ValueError(f"feature_version {manifest.get('feature_version')} != API {F.FEATURE_VERSION}")
        here = T.runtime_fingerprint()
        there = manifest.get("runtime", {})
        skew = {k: (there.get(k), here[k]) for k in ("sklearn", "numpy", "arch") if there.get(k) != here[k]}
        if skew.get("sklearn") and not ALLOW_VERSION_SKEW:
            raise ValueError(f"scikit-learn version skew (notebook, api): {skew['sklearn']}")
        bundle = joblib.load(bpath)
        manifest["_version_skew"] = skew
        return bundle, manifest

    def _build_fallback(self) -> dict:
        if self._fallback is None:
            self._fallback = T.train_all(
                T.bootstrap_series(),
                data_sources={"synthetic_bootstrap": "built into API; no notebook bundle"})
        return self._fallback

    def refresh(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_check < RELOAD_CHECK_SECONDS and self.bundle is not None:
            return
        self._last_check = now
        bpath, mpath = self._paths()
        with self._lock:
            try:
                mtime = os.path.getmtime(mpath) if os.path.exists(mpath) else 0.0
                if mtime and (force or mtime != self._manifest_mtime):
                    bundle, manifest = self._verify_and_load(bpath, mpath)
                    self.bundle, self.manifest = bundle, manifest
                    self.source = "jupyter_shared_volume"
                    self._manifest_mtime = mtime
                    self.last_error = None
                    print(f"[ai] loaded notebook bundle sha256={manifest['sha256'][:12]} "
                          f"trained_at={manifest.get('trained_at')}")
            except Exception as e:  # keep serving the last good model
                self.last_error = f"{type(e).__name__}: {e}"
                self._manifest_mtime = os.path.getmtime(mpath) if os.path.exists(mpath) else 0.0
                print(f"[ai] REJECTED notebook bundle: {self.last_error}")
            if self.bundle is None:
                self.bundle = self._build_fallback()
                self.manifest = {"trained_by": "api-fallback", "runtime": T.runtime_fingerprint(),
                                 "data_sources": self.bundle["data_sources"]}
                self.source = "builtin_fallback"

    def status(self) -> Dict[str, Any]:
        self.refresh()
        m = {k: v for k, v in self.manifest.items() if k != "stations"}
        return {"model_source": self.source,
                "jupyter_linked": self.source == "jupyter_shared_volume",
                "signature_required": bool(MODEL_KEY),
                "last_rejection": self.last_error,
                "manifest": m,
                "stations_with_baselines": len(self.bundle.get("station_stats", {}))}


class ReadingStore:
    """Recent history per series key ("<station>:<flow|stage>") in memory, plus
    an append-only CSV on the shared volume so the notebook can retrain on what
    the API has actually seen."""
    FIELDS = ["station_id", "name", "timestamp", "stage", "flow_cap", "scraped_at"]

    def __init__(self, maxlen: int = 2000) -> None:
        self.hist: Dict[str, Deque[Tuple[str, float]]] = defaultdict(lambda: deque(maxlen=maxlen))
        self.path = os.path.join(SHARED_DIR, "readings.csv")
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, newline="") as f:
                for r in csv.DictReader(f):
                    fc = float(r["flow_cap"]) if r.get("flow_cap") else None
                    sig = D.signal_for(r["station_id"], fc)
                    self._add_mem(D.series_key(r["station_id"], sig), r["timestamp"],
                                  fc if sig == "flow" else float(r["stage"]))
        except Exception as e:
            print(f"[store] could not read {self.path}: {e}")

    def _add_mem(self, key: str, ts: str, value: float) -> bool:
        h = self.hist[key]
        if h and h[-1][0] == ts:
            return False  # same DWS reading scraped again: not new information
        h.append((ts, value))
        return True

    def previous_days(self, key: str, ts: str) -> List[float]:
        """One value per day for the days BEFORE this reading's day (models are daily)."""
        d = F.parse_ts(ts)
        today = d.date().isoformat() if d else ts
        pts = [(t, v) for (t, v) in self.hist.get(key, []) if t != ts]
        return [v for day, v in F.daily_last(pts) if day != today]

    def record(self, key: str, sid: str, name: str, ts: str, value: float,
               stage: float, flow_cap: Optional[float]) -> None:
        with self._lock:
            if not self._add_mem(key, ts, value):
                return
            try:
                os.makedirs(SHARED_DIR, exist_ok=True)
                new = not os.path.exists(self.path)
                with open(self.path, "a", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=self.FIELDS)
                    if new:
                        w.writeheader()
                    w.writerow({"station_id": sid, "name": name, "timestamp": ts, "stage": stage,
                                "flow_cap": "" if flow_cap is None else flow_cap,
                                "scraped_at": datetime.now().isoformat(timespec="seconds")})
            except OSError as e:
                print(f"[store] could not append: {e}")


registry = ModelRegistry()
store = ReadingStore()
_stations_cache: Dict[str, Any] = {"at": 0.0, "reg": {}}

_EXPLAIN = {
    "z_level": "level far from this station's normal range",
    "step_rate": "unusually fast change since the previous day",
    "flatline": "sensor repeating the identical value (possible stuck gauge)",
    "forecast_residual": "reading disagrees with the forecaster's expectation",
    "model_disagreement": "gauge disagrees with GloFAS modelled river flow",
    "rain_context": "change is unusual given recent rainfall",
}


def _stations() -> Dict[str, dict]:
    if time.time() - _stations_cache["at"] > 60:
        _stations_cache.update(at=time.time(), reg=S.load_stations())
    return _stations_cache["reg"]


def live_context(sid: str, signal: str, value: float, ts: str) -> Dict[str, Any]:
    """Independent evidence for this reading: GloFAS flow and 3-day rainfall."""
    st = _stations().get(sid)
    ctx: Dict[str, Any] = {"has_coordinates": bool(st), "glofas_flow_m3s": None,
                           "glofas_next_day_m3s": None, "rain_3d_mm": None,
                           "disagree_raw": float("nan")}
    if not st:
        return ctx
    d = F.parse_ts(ts)
    day = (d or datetime.now()).date().isoformat()
    rain = S.rain_recent(st["lat"], st["lon"], past_days=3)
    ctx["rain_3d_mm"] = S.rain_3day(rain, day)
    if signal == "flow" and not st.get("approx"):
        g = S.glofas_recent(st["lat"], st["lon"], past_days=3, forecast_days=2)
        ctx["glofas_flow_m3s"] = g.get(day)
        nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        ctx["glofas_next_day_m3s"] = g.get(nxt)
        ctx["disagree_raw"] = F.log_disagreement(value, g.get(day))
    return ctx


def _stats_for(bundle: dict, key: str, value: float, prev: List[float]) -> F.StationStats:
    s = bundle["station_stats"].get(key)
    if s:
        return F.StationStats(**s)
    if len(prev) >= F.MIN_HISTORY_FOR_STATS:
        return F.compute_station_stats(prev)
    return F.provisional_stats(value)


def score_reading(sid: str, name: str, stage: float, ts: Optional[str] = None,
                  flow_cap: Optional[float] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    registry.refresh()
    b = registry.bundle
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M")
    signal = D.signal_for(sid, flow_cap)
    value = flow_cap if signal == "flow" else stage
    unit = "m3/s" if signal == "flow" else "m"
    key = D.series_key(sid, signal)
    store.record(key, sid, name, ts, value, stage, flow_cap)
    prev = store.previous_days(key, ts)
    st = _stats_for(b, key, value, prev)
    ctx = live_context(sid, signal, value, ts)

    # Model B forecasts this reading; Model A scores it with Model B's residual,
    # the GloFAS disagreement and rainfall context.
    sp = T.score_point(b, st, prev, value, ctx["disagree_raw"], ctx["rain_3d_mm"])
    xa, raw, is_outlier, trust = sp["xa"], sp["raw"], sp["is_outlier"], sp["trust"]
    fc_next = F.z_to_stage(float(b["forecaster"].predict(F.forecast_row(prev + [value], st)[None])[0]), st)

    reasons: List[str] = []
    if sp["stuck"]:
        reasons.append(_EXPLAIN["flatline"])
    elif sp["guard"]:
        reasons.append(_EXPLAIN[sp["guard"]] + " (beyond trained range)")
    elif is_outlier or trust < REVIEW_BELOW:
        top = int(np.argmax(np.abs(xa)))
        reasons.append(_EXPLAIN[F.ANOMALY_FEATURES[top]])
    if st.n == 0:
        trust = min(trust, 65)
        reasons.append("no baseline for this station yet (trust capped)")
    parsed = F.parse_ts(ts)
    stale_h = F.hours_between(now or datetime.now(), parsed) if parsed else None
    if stale_h is not None and stale_h > STALE_HOURS:
        trust = min(trust, 40)
        reasons.append(f"reading is {stale_h:.0f}h old (source feed stale)")

    status = "review_required" if (is_outlier or sp["stuck"] or sp["guard"] or trust < REVIEW_BELOW or
                                   (stale_h or 0) > STALE_HOURS) else "healthy"
    band = 1.96 * st.step_scale * 1.5
    ctx.pop("disagree_raw")
    return {
        "trust_score": int(np.clip(trust, 0, 100)),
        "status": status,
        "is_outlier": is_outlier,
        "anomaly_score": round(raw, 4),
        "features": {k: round(float(v), 3) for k, v in zip(F.ANOMALY_FEATURES, xa)},
        "reasons": reasons,
        "signal": signal,
        "signal_value": value,
        "unit": unit,
        "expected_range": f"{round(st.median - 2 * st.mad, 2)}{unit} - {round(st.median + 2 * st.mad, 2)}{unit}",
        "forecast": {"predicted_level": round(fc_next, 3),
                     "confidence_interval": f"± {round(band, 3)}{unit}", "unit": unit},
        "context": ctx,
        "reading_timestamp": ts,
        "stale_hours": None if stale_h is None else round(stale_h, 1),
        "history_days": len(prev),
        "station_kind": F.station_kind(sid),
        "model_source": registry.source,
    }
