# HydroLink SA

HydroLink is a water-operations dashboard with a React/Vite frontend and a FastAPI backend. The backend provides station readings, alerts, station summaries, and community-report endpoints.

## Before You Start

Install these tools:

- Git
- Node.js 20.19+ or 22.12+
- Python 3.11+

The commands below use Windows PowerShell. Replace `TheLocalDevIBM2026` if you choose a different folder name when cloning.

## 1. Clone the Project

Open PowerShell and run:

```powershell
git clone https://github.com/kgodisoLeonard/TheLocalDevIBM2026.git
Set-Location .\TheLocalDevIBM2026
```

## 2. Configure the Frontend

Create your local environment file from the example:

```powershell
Copy-Item .env.example .env
```

The default setting points the frontend to the local backend at `http://127.0.0.1:8000/api`. No API key is needed for local development. The `.env` file is ignored by Git; change `VITE_API_BASE_URL` there only if your backend uses another address.

Install frontend packages:

```powershell
npm install
```

## 3. Set Up the Backend

Create a virtual environment and install the Python packages:

```powershell
py -3 -m venv .\hydropolink-backend\.venv
& .\hydropolink-backend\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\hydropolink-backend\.venv\Scripts\python.exe -m pip install -r .\hydropolink-backend\requirements.txt
```

## 4. Start the Backend

Open a PowerShell terminal in the project root and run:

```powershell
Set-Location .\hydropolink-backend
& .\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Leave this terminal running. The API is at <http://127.0.0.1:8000>; interactive API documentation is at <http://127.0.0.1:8000/docs>.

## 5. Start the Frontend

Open a second PowerShell terminal in the project root and run:

```powershell
npm run dev -- --host 127.0.0.1
```

Open the local URL printed by Vite. It is usually <http://127.0.0.1:5173/>. Keep both terminals running while using the app. Press `Ctrl+C` in each terminal to stop its server.

## Troubleshooting

- **The dashboard says the API is unavailable:** Confirm the backend terminal is still running on port 8000, then refresh the frontend.
- **A Python module is missing:** From the project root, rerun the backend `pip install -r` command above using the `.venv` Python executable.
- **Port 8000 is already in use:** Stop the other process using that port before starting this backend.
- **Vite chooses another port:** Open the `Local` URL Vite prints in the frontend terminal.
- **Station data takes a while to appear:** The backend tries to read the live DWS station table; internet access is needed for that source. It supplies sample stations if the source is unavailable.

## Useful Commands

Run these from the project root:

```powershell
npm run build
npm run lint
```

## Machine-Learning Workflow

FastAPI does not train models during startup. Training, threshold tuning, held-out
evaluation and artifact creation are explicit offline operations.

From the project root:

```powershell
Set-Location .\hydropolink-backend
& .\.venv\Scripts\python.exe -m hydrolink_ml train
```

With no `--input`, this creates a reproducible, clearly labelled synthetic development
dataset. It writes chronological data splits under `data/`, validated artifacts under
`hydropolink-backend/artifacts/current/`, and actual executed metrics under `reports/`.
These development metrics are not DWS or SAWS operational results.

To train on an authentic historical export, first standardise its explicit columns:

```powershell
& .\.venv\Scripts\python.exe -m hydrolink_ml ingest `
  ..\data\raw\SOURCE.csv ..\data\processed\canonical-authentic.csv `
  --source "Source organisation, URL, retrieval date and licence" `
  --station-column Station --timestamp-column DateTime --value-column StageMetres

& .\.venv\Scripts\python.exe -m hydrolink_ml train `
  --input ..\data\processed\canonical-authentic.csv
```

The canonical value must be water level in metres; unit conversion is never guessed.
The importer preserves missing observations and provenance and rejects invalid
timestamps. DWS verified downloads are query-limited, while SAWS archived rainfall may
require an authorised data request under the SAWS data policy.

Re-run evaluation or a single prediction with:

```powershell
& .\.venv\Scripts\python.exe -m hydrolink_ml evaluate
& .\.venv\Scripts\python.exe -m hydrolink_ml predict C1H019 0.91 `
  --timestamp 2026-10-09T12:00:00+00:00
```

Start the backend after training:

```powershell
$env:HYDROLINK_MODEL_DIR = (Resolve-Path .\artifacts\current)
& .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

`GET /api/model-info` discloses artifact version, data mode, sources, coverage and
held-out metrics. Missing, incompatible or discontinuous context produces an explicit
unavailable forecast instead of a fabricated prediction. No authoritative flood
thresholds are bundled, so automatic public flood warnings remain disabled until a
responsible authority supplies station-specific thresholds.

Run the tests with:

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
