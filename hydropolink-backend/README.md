# HydroLink SA: hybrid AI on IBM LinuxONE

```
 DWS live feed ──► FastAPI (container: hydrolink-api, s390x) ──► dashboard / alerts / summary
                      │  ▲
          readings.csv│  │ signed model bundle (HMAC-SHA256, hot-reloaded)
                      ▼  │
                 /home/linux1/shared  (Docker volume)
                      ▲  │
                      │  ▼
              Jupyter Lab (container: notebook, same s390x image)
              HydroLink_Train.ipynb: train → evaluate → sign → publish → verify
```

**Models (multi-model hybrid):**
- **Model B, the forecaster** (`HistGradientBoostingRegressor`), predicts each station's next reading from lags normalised per station.
- **Model A, the anomaly detector** (`IsolationForest`), scores level z, rate of change, flatline and Model B's out-of-fold residual. Disagreeing with the forecast is itself evidence that a sensor is faulty.
- **Calibration** maps Model A's score to a 15–99 trust score using clean-data quantiles. A stuck-gauge rule covers the case Isolation Forest can't learn.
- **GenAI** (`genai.py`): an optional OpenAI-compatible LLM writes the summary. Any number it outputs that isn't in the facts gets rejected. Public alerts stay templated.

**Data sources** (`backend/sources.py`, all cached on the shared volume. If a source goes down, the API uses the last good copy, or treats that input as neutral):

| Source | Used for | Notes |
|---|---|---|
| DWS Unverified (scrape) | live readings | timestamp checked; readings older than 6 h are flagged stale |
| Open-Meteo Flood API (GloFAS) | live cross-check + history | modelled, not gauge truth; labelled as such |
| Open-Meteo Forecast / ERA5 Archive | 3-day rainfall context | ERA5 runs about 5 days behind; recent rain comes from the forecast API |
| GRDC gauge files | real training history | download from the GRDC portal → `~/shared/history/grdc/` |
| DWS Verified | real training history | **experimental**: set `USE_DWS_VERIFIED=1` + `DWS_VERIFIED_URL` once checked |

Rivers are scored on **flow (m³/s)** when DWS reports it, so live readings share units with the GRDC and GloFAS history. Dams are scored on stage. The model needs coordinates for GloFAS and rainfall: add verified lat/lon to `~/shared/stations.json`:
```json
{"C1H006": {"name": "Blesbok at Rietvley", "lat": -26.xxxx, "lon": 28.xxxx}}
```
GRDC files are matched to these stations within 3 km. Unmatched GRDC stations still train the shared models.

**Guardrail layer:** Isolation Forest is weak when only one or two features are extreme, for example on a station's first reading, when there's no history yet. Readings get flagged when a feature goes beyond 1.2× the 99.9th percentile seen in training, or when two independent signals (level, movement, GloFAS disagreement) are both strong.

**Security ("AI Secured"):** the API checks the bundle's SHA-256 + HMAC *before* unpickling it, refuses mismatched scikit-learn or feature versions, and keeps serving the last good model when it rejects one. Each decision's audit hash includes the model's SHA, and SHA-256 runs on CPACF on IBM Z.

## Live data: edge collector
DWS's firewall returns **HTTP 403** to overseas cloud IPs, including the LinuxONE Community Cloud. `collector.py` runs on a machine in South Africa, scrapes DWS with the same parser the API uses, and pushes the rows through an SSH tunnel to `POST /api/ingest`. That endpoint requires the `X-HydroLink-Token` header (`HYDROLINK_INGEST_TOKEN`). `GET /api/system` → `dws_feed` shows the mode: `edge_collector`, `direct`, `edge_collector_stale` or `placeholder`. Placeholder stations are always flagged and their trust is capped at 30.

## Deploy (on the VM)
```bash
git clone <your repo> ~/hydrolink-backend && cd ~/hydrolink-backend
bash deploy.sh                      # builds API on the Jupyter base image, starts both containers
# if the build fails:  DOCKERFILE=Dockerfile.ubuntu ALLOW_SKEW=1 bash deploy.sh
```
Check the data sources first: `docker exec hydrolink-api python verify_sources.py` (PASS/FAIL per source).

Open Jupyter → `notebooks/HydroLink_Train.ipynb` → Run All. The last cell asserts the live API is serving the exact SHA it just trained.

`curl localhost:8000/api/system` should now show `"model_source": "jupyter_shared_volume"`, `"architecture": "s390x"`.

`GET /api/sources` shows which data each station was trained on (real gauge, modelled or synthetic).
