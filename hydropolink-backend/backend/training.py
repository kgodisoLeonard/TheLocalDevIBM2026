"""
HydroLink hybrid multi-model training.

  Model B  (forecaster)  HistGradientBoostingRegressor: next reading from lags
  Model A  (anomaly)     IsolationForest on [level z, step rate, flatline,
                         forecast residual]  <- Model B's error feeds Model A
  Calibration            maps Model A's raw score to a 15-99 trust score
                         using the score distribution on clean data.

Called step by step from the Jupyter notebook (the normal path), and by the
API only to build a built-in fallback when no signed notebook bundle exists.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest
from sklearn.model_selection import KFold, cross_val_predict

from . import features as F

STUCK_REPEATS = 3   # identical readings in a row before we call a gauge stuck
REVIEW_BELOW = 50   # trust below this -> human review (~1st percentile of clean data)
STRONG = 4.0        # |feature| this large counts as a "strong" signal
# Features the guardrail inspects (not flatline: has its own rule; not rain: context only)
GUARD_IDX = [0, 1, 3, 4]
BUNDLE_NAME = "hydrolink_models.joblib"
MANIFEST_NAME = "hydrolink_models.manifest.json"


def _aux_at(aux, sid, t):
    """(disagree_raw, rain_3d_mm) for row t of a station; neutral if unknown."""
    if not aux or sid not in aux:
        return float("nan"), None
    d, r = aux[sid][t]
    return float(d), (None if not np.isfinite(r) else float(r))


def fit_station_stats(series: Dict[str, Sequence[float]], aux=None) -> Dict[str, F.StationStats]:
    """aux[sid]: array (n, 2) aligned with series[sid]: [log disagreement, 3-day rain mm], NaN = missing."""
    return {sid: F.compute_station_stats(s, aux[sid][:, 0] if aux and sid in aux else None)
            for sid, s in series.items()
            if len(s) >= F.MIN_HISTORY_FOR_STATS}


def build_forecast_matrix(series, stats):
    Xs, ys, keys = [], [], []
    for sid, s in series.items():
        if sid not in stats:
            continue
        Xf, yf, idx = F.series_to_training_rows(list(s), stats[sid])
        if len(Xf):
            Xs.append(Xf); ys.append(yf); keys += [(sid, int(i)) for i in idx]
    return np.vstack(Xs), np.concatenate(ys), keys


def fit_forecaster(Xf, yf, random_state=42):
    model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05,
                                          max_leaf_nodes=15, random_state=random_state)
    # Out-of-fold predictions: residuals the anomaly model trains on must be
    # honest, not in-sample (in-sample residuals would be unrealistically small).
    n_splits = min(5, max(2, len(yf) // 50))
    oof = cross_val_predict(model, Xf, yf, cv=KFold(n_splits, shuffle=True, random_state=random_state))
    model.fit(Xf, yf)
    return model, oof


def build_anomaly_matrix(series, stats, keys, oof_pred_z, aux=None):
    rows = []
    for (sid, t), pz in zip(keys, oof_pred_z):
        s = series[sid]; st = stats[sid]
        d, r = _aux_at(aux, sid, t)
        rows.append(F.anomaly_row(s[t], s[max(0, t - 24):t], st, F.z_to_stage(pz, st), d, r))
    return np.array(rows)


def fit_anomaly(Xa, contamination=0.01, random_state=42):
    model = IsolationForest(n_estimators=300, contamination=contamination,
                            random_state=random_state)
    model.fit(Xa)
    scores = model.decision_function(Xa)
    return model, scores


def guard_limits(Xa: np.ndarray) -> List[float]:
    """Per-feature hard limit: 1.2x the 99.9th percentile seen on clean training
    data (min 6). Beyond this the forest has never seen anything comparable."""
    q = np.quantile(np.abs(Xa), 0.999, axis=0)
    return [float(max(6.0, 1.2 * v)) for v in q]


def guardrail(xa: np.ndarray, limits: List[float]) -> Optional[str]:
    """Isolation Forest is weak when a point is extreme in only 1-2 of its
    dimensions (e.g. a station's first reading, with no history). Catch those:
    one feature beyond anything seen in training, or two independent strong signals."""
    over = [i for i in GUARD_IDX if abs(xa[i]) > limits[i]]
    if over:
        return F.ANOMALY_FEATURES[over[0]]
    # Independent evidence groups: level | movement (step & forecast error move
    # together on a genuine rain rise, so they count once) | GloFAS disagreement.
    groups = [[0], [1, 3], [4]]
    strong = [max(g, key=lambda i: abs(xa[i])) for g in groups if max(abs(xa[i]) for i in g) > STRONG]
    if len(strong) >= 2:
        return F.ANOMALY_FEATURES[max(strong, key=lambda i: abs(xa[i]))]
    return None


def calibration_knots(clean_scores: np.ndarray) -> Dict[str, List[float]]:
    q = np.quantile(clean_scores, [0.01, 0.05, 0.5, 0.99])
    spread = max(q[2] - q[0], 1e-3)
    xs = [q[0] - 2 * spread, q[0], q[1], q[2], q[3]]
    ys = [15, 50, 70, 90, 99]
    # np.interp needs strictly increasing x
    for i in range(1, len(xs)):
        xs[i] = max(xs[i], xs[i - 1] + 1e-6)
    return {"x": [float(v) for v in xs], "y": ys}


def make_bundle(forecaster, anomaly, stats, calib, data_sources, metrics, limits=None):
    return {
        "guard_limits": limits,
        "forecaster": forecaster,
        "anomaly": anomaly,
        "station_stats": {k: v.to_dict() for k, v in stats.items()},
        "calibration": calib,
        "feature_version": F.FEATURE_VERSION,
        "anomaly_features": F.ANOMALY_FEATURES,
        "forecast_features": F.FORECAST_FEATURES,
        "data_sources": data_sources,
        "metrics": metrics,
    }


def runtime_fingerprint() -> Dict[str, str]:
    return {"arch": platform.machine(), "python": platform.python_version(),
            "sklearn": sklearn.__version__, "numpy": np.__version__}


def save_signed_bundle(bundle: dict, out_dir: str, key: str | None, trained_by: str) -> dict:
    """Write bundle + manifest. Manifest carries SHA-256 and HMAC-SHA256 of the
    bundle bytes; the API refuses to unpickle anything that doesn't verify.
    Bundle is written to a temp name then renamed, so the API never sees a
    half-written file."""
    import joblib
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, BUNDLE_NAME)
    tmp = path + ".tmp"
    joblib.dump(bundle, tmp)
    data = open(tmp, "rb").read()
    manifest = {
        "bundle": BUNDLE_NAME,
        "sha256": hashlib.sha256(data).hexdigest(),
        "hmac_sha256": hmac.new(key.encode(), data, hashlib.sha256).hexdigest() if key else None,
        "signed": bool(key),
        "feature_version": F.FEATURE_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trained_by": trained_by,
        "runtime": runtime_fingerprint(),
        "data_sources": bundle.get("data_sources", {}),
        "metrics": bundle.get("metrics", {}),
        "stations": sorted(bundle["station_stats"].keys()),
    }
    os.replace(tmp, path)
    mtmp = os.path.join(out_dir, MANIFEST_NAME + ".tmp")
    with open(mtmp, "w") as f:
        json.dump(manifest, f, indent=2)
    os.replace(mtmp, os.path.join(out_dir, MANIFEST_NAME))   # manifest last = commit point
    return manifest


def train_all(series: Dict[str, Sequence[float]], data_sources: dict, contamination=0.01, aux=None):
    """End-to-end convenience used by the API fallback (the notebook runs the
    same steps one cell at a time)."""
    stats = fit_station_stats(series, aux)
    Xf, yf, keys = build_forecast_matrix(series, stats)
    forecaster, oof = fit_forecaster(Xf, yf)
    Xa = build_anomaly_matrix(series, stats, keys, oof, aux)
    anomaly, scores = fit_anomaly(Xa, contamination)
    calib = calibration_knots(scores)
    limits = guard_limits(Xa)
    mae_model = float(np.mean(np.abs(oof - yf)))
    mae_persist = float(np.mean(np.abs(Xf[:, 0] - yf)))
    metrics = {"forecast_mae_z": mae_model, "persistence_mae_z": mae_persist,
               "rows": int(len(yf))}
    return make_bundle(forecaster, anomaly, stats, calib, data_sources, metrics, limits)


def bootstrap_series(seed=7) -> Dict[str, np.ndarray]:
    """Labelled synthetic history for the two demo stations (fallback only)."""
    rng = np.random.default_rng(seed)
    return {"C1H019:stage": F.synthetic_series(0.85, 1500, rng, "river"),
            "C1R002:stage": F.synthetic_series(27.2, 1500, rng, "dam"),
            "C1H006:stage": F.synthetic_series(0.55, 1500, rng, "river")}


def score_point(bundle: dict, st: F.StationStats, prev: Sequence[float], stage: float,
                disagree_raw: float = float("nan"), rain_3d_mm=None) -> dict:
    """Core hybrid scoring for one reading. Shared by the API and the
    notebook's evaluation so the numbers you report are the numbers you serve."""
    prev = list(prev)
    fc_this = (F.z_to_stage(float(bundle["forecaster"].predict(F.forecast_row(prev, st)[None])[0]), st)
               if prev else None)
    xa = F.anomaly_row(stage, prev[-24:], st, fc_this, disagree_raw, rain_3d_mm)
    raw = float(bundle["anomaly"].decision_function(xa[None])[0])
    cal = bundle["calibration"]
    trust = int(round(float(np.interp(raw, cal["x"], cal["y"]))))
    # Stuck-gauge rule. Isolation Forest can't learn this: clean training data
    # never repeats exactly, so that feature is constant and never split on.
    stuck = xa[2] * 24 >= STUCK_REPEATS and F.station_kind_noisy(st)
    if stuck:
        trust = min(trust, 35)
    guard = guardrail(xa, bundle["guard_limits"]) if bundle.get("guard_limits") else None
    if guard:
        trust = min(trust, 40)
    return {"xa": xa, "raw": raw, "stuck": bool(stuck), "guard": guard,
            "is_outlier": int(bundle["anomaly"].predict(xa[None])[0]) == -1,
            "trust": trust, "forecast_this": fc_this}
