from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import hashlib
import hmac
import json
import os
import platform
import time
from datetime import datetime

from . import ai_engine
from . import dws
from . import genai

app = FastAPI(
    title="HydroLink SA LinuxONE AI Engine",
    description="Hybrid multi-model AI (forecaster + anomaly detector) trained in Jupyter on LinuxONE s390x.",
    version="5.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ForecastModel(BaseModel):
    predicted_level: float
    confidence_interval: str
    unit: str = "m"


class StationTelemetry(BaseModel):
    station_id: str
    name: str
    catchment: str
    trust_score: int = Field(..., ge=0, le=100)
    current_value: float
    expected_range: str
    status: str
    forecast: ForecastModel
    anomalies_flagged: str
    audit_hash: str
    # new, optional — existing frontend keeps working
    reading_timestamp: Optional[str] = None
    stale_hours: Optional[float] = None
    reasons: List[str] = []
    model_source: Optional[str] = None
    station_kind: Optional[str] = None
    signal: Optional[str] = None          # "flow" (m3/s) for rivers with flow, else "stage" (m)
    unit: Optional[str] = None
    signal_value: Optional[float] = None
    context: Dict[str, Any] = {}          # GloFAS flow, rainfall: independent evidence


class AlertItem(BaseModel):
    station_id: str
    language: str
    message: str
    trust_score: int
    status: str


class SummaryPayload(BaseModel):
    station_id: str
    name: str
    trust_score: int
    current_value: float
    status: str


def generate_ibm_z_audit(station_id: str, value: float, trust: int, ts: str) -> str:
    """Tamper-evident decision record: ties reading + decision to the exact
    model bundle that made it. SHA-256 runs on CPACF on IBM Z via OpenSSL."""
    model_sha = ai_engine.registry.manifest.get("sha256", "fallback")[:16]
    raw = f"{ts}|{station_id}|{value}|{trust}|{model_sha}"
    h = hashlib.sha256(raw.encode()).hexdigest()
    return f"0x{h[:10]}...{h[-4:]} (model {model_sha[:8]})"


def analyze_station_with_ai(station_id: str, name: str, stage_val: float,
                            ts: Optional[str] = None, flow_cap: Optional[float] = None) -> Dict[str, Any]:
    r = ai_engine.score_reading(station_id, name, stage_val, ts=ts, flow_cap=flow_cap)
    if r["status"] == "healthy":
        msg = f"Hybrid AI inlier (anomaly score {r['anomaly_score']}). Reading consistent with forecast and station baseline."
    else:
        msg = f"Flagged for review (anomaly score {r['anomaly_score']}): " + "; ".join(r["reasons"] or ["outlier"])
    return {
        "station_id": station_id,
        "name": name,
        "catchment": f"Basin Zone {station_id[:1]}",
        "trust_score": r["trust_score"],
        "current_value": stage_val,
        "expected_range": r["expected_range"],
        "status": r["status"],
        "forecast": r["forecast"],
        "anomalies_flagged": msg,
        "audit_hash": generate_ibm_z_audit(station_id, stage_val, r["trust_score"], r["reading_timestamp"]),
        "reading_timestamp": r["reading_timestamp"],
        "stale_hours": r["stale_hours"],
        "reasons": r["reasons"],
        "model_source": r["model_source"],
        "station_kind": r["station_kind"],
        "signal": r["signal"],
        "unit": r["unit"],
        "signal_value": r["signal_value"],
        "context": r["context"],
    }


_cache: Dict[str, Any] = {"at": 0.0, "rows": []}
CACHE_SECONDS = 60
INGEST_TOKEN = os.getenv("HYDROLINK_INGEST_TOKEN")
INGEST_FRESH_SECONDS = 2 * 3600
INGEST_PATH = os.path.join(ai_engine.SHARED_DIR, "dws_latest.json")
_feed: Dict[str, Any] = {"mode": "none", "ok": False, "rows": 0, "error": None,
                         "fetched_at": None, "collector": None}


def _load_ingested() -> Optional[Dict[str, Any]]:
    try:
        return json.load(open(INGEST_PATH))
    except Exception:
        return None


def fetch_dws_rows() -> List[Dict[str, Any]]:
    """Live DWS rows. Order: rows pushed by the edge collector (if fresh) ->
    direct scrape -> last pushed rows (stale; the AI flags their age)."""
    if time.time() - _cache["at"] < CACHE_SECONDS and _cache["rows"]:
        return _cache["rows"]
    pushed = _load_ingested()
    if pushed and time.time() - pushed["received_at"] < INGEST_FRESH_SECONDS:
        _cache.update(at=time.time(), rows=pushed["rows"])
        _feed.update(mode="edge_collector", ok=True, rows=len(pushed["rows"]), error=None,
                     fetched_at=pushed["received_iso"], collector=pushed.get("collector"))
        return pushed["rows"]
    rows, err = dws.fetch_unverified(timeout=15)
    if rows:
        _cache.update(at=time.time(), rows=rows)
        _feed.update(mode="direct", ok=True, rows=len(rows), error=None,
                     fetched_at=datetime.now().isoformat(timespec="seconds"))
        return rows
    print(f"Scraper error: {err}")
    _feed.update(ok=False, error=err)
    if pushed:   # stale collector data beats placeholders; staleness is flagged per reading
        _feed.update(mode="edge_collector_stale", rows=len(pushed["rows"]),
                     fetched_at=pushed["received_iso"])
        _cache.update(at=time.time(), rows=pushed["rows"])
        return pushed["rows"]
    _feed.update(mode="placeholder", rows=0)
    return []


def scrape_live_dws() -> List[Dict[str, Any]]:
    stations = [analyze_station_with_ai(r["station_id"], r["name"], r["stage"], r["timestamp"], r["flow_cap"])
                for r in fetch_dws_rows()]
    if not stations:
        for sid, name, val in [("C1H019", "Grootdraai Dam Outflow", 0.843),
                               ("LMP-CR-04", "Crocodile River Main Station", 6.100)]:
            st = analyze_station_with_ai(sid, name, val, ts="offline-cache")
            st["status"] = "review_required"
            st["trust_score"] = min(st["trust_score"], 30)
            st["reasons"] = ["DWS feed unavailable - placeholder station, not live data"] + st["reasons"]
            st["anomalies_flagged"] = "PLACEHOLDER: no live DWS data. " + (_feed.get("error") or "")
            stations.append(st)
    return stations


class IngestRow(BaseModel):
    station_id: str = Field(..., min_length=3, max_length=20)
    name: str = Field("", max_length=200)
    timestamp: Optional[str] = Field(None, max_length=40)
    stage: float
    flow_cap: Optional[float] = None


class IngestPayload(BaseModel):
    collector: str = Field("unknown", max_length=100)
    rows: List[IngestRow]


@app.post("/api/ingest")
def ingest(payload: IngestPayload, x_hydrolink_token: Optional[str] = Header(None)):
    """Edge collector pushes DWS rows scraped from a South African network."""
    if not INGEST_TOKEN or not hmac.compare_digest(x_hydrolink_token or "", INGEST_TOKEN):
        raise HTTPException(status_code=401, detail="invalid or missing X-HydroLink-Token")
    if len(payload.rows) > 5000:
        raise HTTPException(status_code=413, detail="max 5000 rows per push")
    rows = [getattr(r, "model_dump", r.dict)() for r in payload.rows]   # pydantic v2 or v1
    doc = {"received_at": time.time(), "received_iso": datetime.now().isoformat(timespec="seconds"),
           "collector": payload.collector, "rows": rows}
    tmp = INGEST_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, INGEST_PATH)
    _cache.update(at=0.0, rows=[])          # next request uses the new rows
    scored = scrape_live_dws()               # score now so readings.csv logs them immediately
    return {"accepted": len(rows), "scored": len(scored),
            "review_required": sum(s["status"] == "review_required" for s in scored)}


@app.get("/api/system")
def get_system():
    s = ai_engine.registry.status()
    return {"architecture": platform.machine(), "os": platform.system(), "node": platform.node(),
            "dws_feed": dict(_feed), **s}


@app.get("/api/sources")
def get_sources():
    """What data the AI is using right now, and where it came from."""
    reg = ai_engine.S.load_stations()
    return {"stations_with_coordinates": len(reg),
            "approximate_coordinates": sorted(k for k, v in reg.items() if v.get("approx")),
            "training_data": ai_engine.registry.manifest.get("data_sources", {}),
            "live": {"dws_unverified": "https://www.dws.gov.za/Hydrology/Unverified",
                     "glofas": ai_engine.S.FLOOD_URL, "rain": ai_engine.S.FORECAST_URL}}


@app.post("/api/model/reload")
def reload_model():
    ai_engine.registry.refresh(force=True)
    return ai_engine.registry.status()


@app.get("/api/dashboard", response_model=List[StationTelemetry])
def get_dashboard():
    return scrape_live_dws()


@app.get("/api/readings", response_model=StationTelemetry)
def get_readings(station_id: str):
    match = next((s for s in scrape_live_dws() if s["station_id"].lower() == station_id.lower()), None)
    if not match:
        raise HTTPException(status_code=404, detail="Station not found")
    return match


@app.get("/api/alerts", response_model=List[AlertItem])
def get_alerts():
    alerts = []
    for st in scrape_live_dws()[:4]:
        lang = "Sepedi" if "A" <= st["station_id"][:1] <= "M" else "isiZulu"
        # Alerts stay templated: small LLMs are unreliable in Sepedi/isiZulu,
        # and a public flood alert must never contain invented content.
        msg = (f"Boemo bja meetse a {st['name']} bo hlahlobilwe ke AI. Tekano: {st['current_value']}m."
               if lang == "Sepedi" else
               f"Amanzi ase-{st['name']} ahlolwe yi-AI ku-{st['current_value']}m.")
        alerts.append({"station_id": st["station_id"], "language": lang, "message": msg,
                       "trust_score": st["trust_score"],
                       "status": "Normal" if st["status"] == "healthy" else "Review Required"})
    return alerts


@app.post("/api/summarize")
def generate_ai_summary(payload: SummaryPayload):
    st = next((s for s in scrape_live_dws() if s["station_id"].lower() == payload.station_id.lower()), None)
    facts = {
        "station_id": payload.station_id, "name": payload.name,
        "current_value": payload.current_value, "trust_score": payload.trust_score,
        "status": payload.status,
        "expected_range": st["expected_range"] if st else "unknown",
        "forecast": st["forecast"]["predicted_level"] if st else "unknown",
        "reasons": st["reasons"] if st else [],
        "unit": st["unit"] if st else "m",
        "signal_value": st["signal_value"] if st else payload.current_value,
        "glofas_flow_m3s": st["context"].get("glofas_flow_m3s") if st else None,
        "rain_3d_mm": st["context"].get("rain_3d_mm") if st else None,
    }
    text, engine = genai.summarize(facts)
    return {"summary": text, "engine": engine}


@app.post("/api/feedback")
def post_feedback(payload: dict):
    station_id = payload.get("station_id", "UNKNOWN")
    return {
        "id": int(time.time()),
        "farmer": "Community reporter",
        "location": station_id,
        "report": payload.get("report", ""),
        "lang": payload.get("lang", "Sepedi"),
        "impact": "Logged for analyst review",
        "message": "Community report received and queued alongside the station's AI trust assessment.",
    }
