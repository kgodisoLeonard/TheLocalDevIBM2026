"""Generates HydroLink_Train.ipynb. Run: python3 build_notebook.py"""
import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []
md = lambda s: C.append(nbf.v4.new_markdown_cell(s))
code = lambda s: C.append(nbf.v4.new_code_cell(s))

md("""# HydroLink SA: hybrid AI training on IBM LinuxONE (s390x)

This notebook is where the models are trained. The FastAPI service only serves them.

| Step | What happens |
|---|---|
| 1 | Check this kernel matches the API container (arch, scikit-learn, numpy) |
| 2 | Build the training set from **GRDC gauge history**, **DWS Verified** (opt-in), **GloFAS modelled discharge**, **ERA5 rainfall** and the API's own **DWS live log** |
| 3 | **Model B** is a gradient-boosted forecaster that predicts each station's next day |
| 4 | **Model A** is an Isolation Forest on level, rate of change, flatline, *Model B's residual*, *gauge-vs-GloFAS disagreement* and *rainfall context* |
| 5 | Evaluate against injected sensor faults (spike, flatline, drift, dropout) |
| 6 | Sign the bundle (HMAC-SHA256) and publish it to `/shared`. The API verifies and hot-reloads it |
| 7 | Ask the live API to confirm it is serving this exact bundle |
""")

code("""import os, sys, json, platform
sys.path.insert(0, os.path.expanduser('~'))          # ~/backend is mounted read-only from the repo
import numpy as np
import requests
from backend import features as F, training as T, sources as S, datasets as D

SHARED  = os.path.expanduser('~/shared')
S.SHARED_DIR = SHARED; S.CACHE_DIR = os.path.join(SHARED, 'cache')   # same volume, notebook-side path
API     = os.getenv('HYDROLINK_API', 'http://hydrolink-api:8000')
KEY     = os.getenv('HYDROLINK_MODEL_KEY')
print('Kernel runtime :', T.runtime_fingerprint())
print('Feature version:', F.FEATURE_VERSION, '| signing key set:', bool(KEY))
try:
    api = requests.get(f'{API}/api/system', timeout=5).json()
    print('API runtime    :', api['manifest'].get('runtime'), '| currently serving:', api['model_source'])
    if api['manifest'].get('runtime', {}).get('sklearn') not in (None, T.runtime_fingerprint()['sklearn']):
        print('WARNING: scikit-learn differs between notebook and API, so the API will reject this bundle.')
except Exception as e:
    print('API not reachable yet (', e, '). Training still works; the verify cell will fail.')""")

md("""## 1. Station registry
GloFAS and rainfall need coordinates. Put verified lat/lon from the DWS Station Catalogue in `~/shared/stations.json`:
```json
{"C1H006": {"name": "Blesbok at Rietvley", "lat": -26.000, "lon": 28.000}}
```
Coordinates flagged `approx` get rainfall only, never the GloFAS check.""")
code("""stations = S.load_stations()
for sid, st in stations.items():
    print(f"{sid:8s} {st.get('name',''):32s} {st['lat']:9.4f} {st['lon']:9.4f} {'APPROX' if st.get('approx') else ''}")
print(len(stations), 'stations with coordinates')""")

md("""## 2. Build the training set
Each station uses its best source, in this order: real gauge (GRDC file in `~/shared/history/grdc/`, or DWS Verified if `USE_DWS_VERIFIED=1`), then GloFAS modelled, then the live log. Every station's source is written to the manifest.""")
code("""series, aux, report = D.build_training_set(use_dws_verified=os.getenv('USE_DWS_VERIFIED') == '1')

# Stations seen live but without enough history: labelled synthetic bootstrap
# anchored on their real observed level, so the API still has a baseline.
rng = np.random.default_rng(42)
synthetic = []
for key, vals in D.load_logged_readings().items():
    if key not in series and len(vals) >= 1:
        base = float(np.median(list(vals.values())))
        series[key] = F.synthetic_series(base, 600, rng, F.station_kind(key))
        aux[key] = np.full((600, 2), np.nan); synthetic.append(key)
if not series:
    for k, v in T.bootstrap_series().items():
        series[k] = v; aux[k] = np.full((len(v), 2), np.nan); synthetic.append(k)
sources = {'per_series': report, 'synthetic_bootstrap': synthetic,
           'real_gauge_series': sorted(k for k, r in report.items() if r['real_gauge']),
           'modelled_series': sorted(k for k, r in report.items() if not r['real_gauge'])}
print({k: len(v) for k, v in sources.items() if isinstance(v, list)})""")

md("## 3. Time-ordered split (no future leakage)")
code("""train, test, aux_tr, aux_te = {}, {}, {}, {}
for k, s in series.items():
    cut = int(len(s) * 0.8)
    train[k], test[k] = s[:cut], s[cut:]
    aux_tr[k], aux_te[k] = aux[k][:cut], aux[k][cut:]
stats = T.fit_station_stats(train, aux_tr)
print('series with baselines:', len(stats))""")

md("## 4. Model B: forecaster (HistGradientBoostingRegressor)")
code("""Xf, yf, keys = T.build_forecast_matrix(train, stats)
forecaster, oof = T.fit_forecaster(Xf, yf)

err_m, err_p = [], []   # relative errors so flow (m3/s) and stage (m) series are comparable
for k, s in test.items():
    if k not in stats: continue
    full = np.concatenate([train[k], s]); off = len(train[k]); st = stats[k]
    for t in range(off, len(full)):
        pred = F.z_to_stage(float(forecaster.predict(F.forecast_row(full[t-3:t], st)[None])[0]), st)
        err_m.append(abs(pred - full[t]) / st.mad); err_p.append(abs(full[t-1] - full[t]) / st.mad)
mae_m, mae_p = float(np.mean(err_m)), float(np.mean(err_p))
print(f'Test MAE (station-normalised)  model: {mae_m:.3f}   persistence: {mae_p:.3f}   '
      f'improvement: {100*(1-mae_m/mae_p):.1f}%')""")

md("## 5. Model A: Isolation Forest on engineered features")
code("""Xa = T.build_anomaly_matrix(train, stats, keys, oof, aux_tr)
anomaly, train_scores = T.fit_anomaly(Xa)
calib = T.calibration_knots(train_scores)
limits = T.guard_limits(Xa)
print('guardrail limits:', dict(zip(F.ANOMALY_FEATURES, np.round(limits, 2))))
print('features:', F.ANOMALY_FEATURES)
print('share of rows with a live GloFAS check:', round(float(np.mean(Xa[:, 4] != 0)), 3),
      '| with rainfall:', round(float(np.mean(Xa[:, 5] != 0)), 3))""")

md("## 6. Evaluate on injected sensor faults (held-out data)")
code("""bundle = T.make_bundle(forecaster, anomaly, stats, calib, sources, {}, limits)
tp = fp = fn = tn = 0; per_type = {k: [0, 0] for k in F.FAULT_TYPES}
example = None
for k, s in test.items():
    if k not in stats: continue
    corrupted, mask, kinds = F.inject_faults(s, rng)
    full = np.concatenate([train[k], corrupted]); off = len(train[k])
    flags = []
    for i in range(len(corrupted)):
        d_raw, r3 = aux_te[k][i]
        if np.isfinite(d_raw):   # the fault also corrupts the gauge side of the GloFAS comparison
            d_raw = d_raw + np.log1p(max(corrupted[i], 0)) - np.log1p(max(s[i], 0))
        r = T.score_point(bundle, stats[k], full[:off+i][-24:], full[off+i], d_raw,
                          None if not np.isfinite(r3) else r3)
        flag = r['is_outlier'] or r['stuck'] or bool(r['guard']) or r['trust'] < T.REVIEW_BELOW; flags.append(flag)
        if mask[i]:
            per_type[kinds[i]][1] += 1; per_type[kinds[i]][0] += flag; tp += flag; fn += not flag
        else:
            fp += flag; tn += not flag
    if example is None or (k in sources['real_gauge_series'] and example[0] not in sources['real_gauge_series']):
        example = (k, corrupted, mask, np.array(flags))
prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1); f1 = 2*prec*rec / max(prec + rec, 1e-9)
fpr = fp / max(fp + tn, 1)
print(f'precision {prec:.2f}  recall {rec:.2f}  F1 {f1:.2f}  false-alarm rate {fpr:.3f}')
for kind, (hit, n) in per_type.items():
    print(f'  {kind:9s} caught {hit}/{n}')
# Day-one check: a station's very first reading has no history, so only level and
# GloFAS disagreement can speak. Score faults with an empty history.
d1_hit = d1_n = d1_fp = d1_clean = 0
for k, s in test.items():
    if k not in stats: continue
    corrupted, mask, kinds = F.inject_faults(s, np.random.default_rng(7))
    for i in range(len(corrupted)):
        if kinds[i] == 'flatline': continue          # needs history by definition
        d_raw, r3 = aux_te[k][i]
        if np.isfinite(d_raw):
            d_raw = d_raw + np.log1p(max(corrupted[i], 0)) - np.log1p(max(s[i], 0))
        r = T.score_point(bundle, stats[k], [], corrupted[i], d_raw, None if not np.isfinite(r3) else r3)
        flag = r['is_outlier'] or bool(r['guard']) or r['trust'] < T.REVIEW_BELOW
        if mask[i]: d1_n += 1; d1_hit += flag
        else: d1_clean += 1; d1_fp += flag
print(f'day-one (no history): caught {d1_hit}/{d1_n} faults, false alarms {d1_fp/max(d1_clean,1):.3f}')
metrics = {'day_one_recall': d1_hit / max(d1_n, 1), 'day_one_false_alarm': d1_fp / max(d1_clean, 1),
           'forecast_mae_norm': mae_m, 'persistence_mae_norm': mae_p, 'fault_precision': prec,
           'fault_recall': rec, 'fault_f1': f1, 'false_alarm_rate': fpr,
           'per_fault_recall': {k: (h / n if n else None) for k, (h, n) in per_type.items()}}""")

code("""import matplotlib.pyplot as plt
k, s, mask, flags = example
fig, ax = plt.subplots(figsize=(12, 3.5))
ax.plot(s, lw=1, label='held-out series (with injected faults)')
ax.scatter(np.where(mask)[0], s[mask], marker='x', s=40, label='injected fault', zorder=3)
ax.scatter(np.where(flags)[0], s[flags], facecolors='none', edgecolors='r', s=80, label='AI flagged', zorder=4)
src = report.get(k, {}).get('source', 'synthetic bootstrap')
ax.set_title(f'{k} [{src}] on LinuxONE {platform.machine()}'); ax.legend()
plt.tight_layout(); plt.savefig(os.path.join(SHARED, 'eval_plot.png'), dpi=120); plt.show()""")

md("## 7. Refit on all data, sign, publish to the shared volume")
code("""stats_all = T.fit_station_stats(series, aux)
Xf, yf, keys = T.build_forecast_matrix(series, stats_all)
forecaster, oof = T.fit_forecaster(Xf, yf)
Xa_all = T.build_anomaly_matrix(series, stats_all, keys, oof, aux)
anomaly, scores = T.fit_anomaly(Xa_all)
final = T.make_bundle(forecaster, anomaly, stats_all, T.calibration_knots(scores), sources, metrics,
                      T.guard_limits(Xa_all))
manifest = T.save_signed_bundle(final, SHARED, KEY, trained_by=f'jupyter@{platform.node()}')
print(json.dumps({k: manifest[k] for k in ('sha256', 'signed', 'trained_at', 'runtime')}, indent=2))""")

md("## 8. Prove the live API is serving this exact bundle")
code("""r = requests.post(f'{API}/api/model/reload', timeout=30).json()
print('API source   :', r['model_source'], '| jupyter_linked:', r['jupyter_linked'])
print('API rejection:', r['last_rejection'])
assert r['manifest'].get('sha256') == manifest['sha256'], 'API is NOT serving the bundle just trained'
print('OK: API on', requests.get(f'{API}/api/system').json()['architecture'],
      'is serving sha256', manifest['sha256'][:16])
print(json.dumps(requests.get(f'{API}/api/dashboard', timeout=60).json()[:2], indent=2))""")

nb["cells"] = C
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, "HydroLink_Train.ipynb")
print("wrote HydroLink_Train.ipynb")
