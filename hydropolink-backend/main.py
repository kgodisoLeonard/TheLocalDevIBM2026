from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List

app = FastAPI(
    title="HydroLink SA Backend API",
    description="Real-time AI Trust Layer & Multi-Source Validation API for South Africa.",
    version="1.0.0"
)

# Enable CORS so your React frontend can communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Schemas ---
class ForecastModel(BaseModel):
    predicted_level: float
    confidence_interval: str

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

class AlertItem(BaseModel):
    station_id: str
    language: str
    message: str
    trust_score: int
    status: str

# --- Mock Data Stores ---
DASHBOARD_DB = [
    {
        "station_id": "LMP-SD-01",
        "name": "Sand River Upstream Weir",
        "catchment": "Limpopo (Sand/Crocodile)",
        "trust_score": 88,
        "current_value": 4.2,
        "expected_range": "3.9m - 4.4m",
        "status": "healthy",
        "forecast": {"predicted_level": 4.3, "confidence_interval": "± 0.2m"},
        "anomalies_flagged": "Normal behavior. 0.4 standard deviations from baseline. Rainfall verified via SAWS."
    },
    {
        "station_id": "LMP-CR-04",
        "name": "Crocodile River Main Station",
        "catchment": "Limpopo (Sand/Crocodile)",
        "trust_score": 42,
        "current_value": 6.1,
        "expected_range": "2.1m - 2.5m",
        "status": "missing",
        "forecast": {"predicted_level": 2.3, "confidence_interval": "± 0.5m"},
        "anomalies_flagged": "Anomaly Triggered: Stale/Spike detected (4.1 std deviations). Trust-gated alert withheld to prevent false panic."
    }
]

ALERTS_DB = [
    {"station_id": "LMP-SD-01", "language": "Sepedi", "message": "Go na le mohlodi wa meetsi a mantsi mo nokeng ya Sand. Tshedimosetso e netefaditswe.", "trust_score": 88, "status": "Caution"},
    {"station_id": "LMP-CR-04", "language": "isiZulu", "message": "Amanzi asezingeni eliphezulu endaweni yaseCrocodile. Qaphela ngaphambi kokuwela.", "trust_score": 42, "status": "Review Required"},
    {"station_id": "LMP-SD-01", "language": "Afrikaans", "message": "Sandrivier vlakte stabiel. Geen direkte oorstromingsrisiko nie.", "trust_score": 88, "status": "Normal"}
]

# --- API Endpoints ---
@app.get("/api/dashboard", response_model=List[StationTelemetry])
def get_dashboard():
    """Provides feed health and metadata for municipal officials."""
    return DASHBOARD_DB

@app.get("/api/readings", response_model=StationTelemetry)
def get_readings(station_id: str):
    """Fetches validated water readings, trust scores, and anomalies for a specific station."""
    station = next((s for s in DASHBOARD_DB if s["station_id"] == station_id), None)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    return station

@app.get("/api/alerts", response_model=List[AlertItem])
def get_alerts():
    """Fetches multilingual alerts (Sepedi, isiZulu, Afrikaans) for farmers and communities."""
    return ALERTS_DB

@app.post("/api/feedback")
def post_feedback(payload: dict):
    """Processes farmer WhatsApp/text reports and updates trust scores."""
    return {
        "id": 99,
        "farmer": "Smallholder Farmer (Simulated)",
        "location": payload.get("station_id", "LMP-SD-01"),
        "report": payload.get("report"),
        "lang": payload.get("lang"),
        "impact": "+5 Trust Boost Applied via Community Cross-Check",
        "message": "Successfully recorded community report & updated local station trust score."
    }