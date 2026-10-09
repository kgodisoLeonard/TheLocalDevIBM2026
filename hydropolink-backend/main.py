"""HydroLink SA FastAPI application backed by offline model artifacts."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hydrolink_ml.config import ARTIFACT_ROOT
from hydrolink_ml.inference import HydroLinkInferenceService
from scraper import fetch_live_dws_stations


LOGGER = logging.getLogger(__name__)
MODEL_DIRECTORY = Path(os.getenv("HYDROLINK_MODEL_DIR", str(ARTIFACT_ROOT / "current")))
INFERENCE = HydroLinkInferenceService(MODEL_DIRECTORY)

app = FastAPI(
    title="HydroLink SA Hydrological Trust Engine",
    description="Validated anomaly detection, forecasting, uncertainty and explainable Trust Scores.",
    version="4.0.0",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("HYDROLINK_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ForecastModel(BaseModel):
    predicted_level: float | None
    confidence_interval: str
    lower_bound: float | None = None
    upper_bound: float | None = None
    coverage_target: float | None = None
    horizon_hours: int | None = None
    algorithm: str | None = None
    model_available: bool = False
    unavailable_reason: str | None = None


class StationTelemetry(BaseModel):
    station_id: str
    name: str
    catchment: str
    timestamp: str
    source: str
    trust_score: int = Field(..., ge=0, le=100)
    trust_components: dict[str, Any]
    trust_explanation: str
    current_value: float | None
    expected_range: str
    status: str
    forecast: ForecastModel
    anomaly: bool
    anomaly_reasons: list[str]
    anomalies_flagged: str
    isolation_score: float | None
    model_scope: str
    model_info: dict[str, Any]
    alert: dict[str, Any]
    audit_hash: str


class AlertItem(BaseModel):
    station_id: str
    language: str
    message: str
    trust_score: int
    status: str
    risk_level: str
    reason: str
    requires_human_review: bool


class SummaryPayload(BaseModel):
    station_id: str
    name: str
    trust_score: int
    current_value: float | None
    status: str
    anomaly_reasons: list[str] = Field(default_factory=list)


def generate_local_audit_digest(station_id: str, timestamp: str, value: float | None, trust: int) -> str:
    """Create a local integrity digest; this is not IBM Z persistence."""
    raw = f"{timestamp}|{station_id}|{value}|{trust}"
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _fallback_stations() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "station_id": "C1H019",
            "name": "Grootdraai Dam Outflow (development fallback)",
            "timestamp": now,
            "current_value": 0.843,
            "source": "synthetic_fallback_not_dws",
        },
        {
            "station_id": "LMP-CR-04",
            "name": "Crocodile River Development Station",
            "timestamp": now,
            "current_value": 2.31,
            "source": "synthetic_fallback_not_dws",
        },
    ]


def _raw_stations() -> list[dict[str, Any]]:
    try:
        return fetch_live_dws_stations()
    except (requests.RequestException, ValueError) as exc:
        LOGGER.warning("Using labelled development fallback because DWS is unavailable: %s", exc)
        return _fallback_stations()


def _analyse(raw: dict[str, Any]) -> dict[str, Any]:
    result = INFERENCE.analyze(
        station_id=str(raw["station_id"]),
        name=str(raw.get("name") or raw["station_id"]),
        value_m=raw.get("current_value"),
        timestamp=str(raw["timestamp"]),
        received_at=datetime.now(timezone.utc),
        source=str(raw.get("source") or "unknown"),
        as_of=datetime.now(timezone.utc),
    )
    result["audit_hash"] = generate_local_audit_digest(
        result["station_id"], result["timestamp"], result["current_value"], result["trust_score"]
    )
    return result


def get_analyzed_stations() -> list[dict[str, Any]]:
    return [_analyse(raw) for raw in _raw_stations()]


@app.get("/api/health")
def get_health() -> dict[str, object]:
    return {"status": "ok", "model_available": INFERENCE.available, "model_directory": str(MODEL_DIRECTORY)}


@app.get("/api/model-info")
def get_model_info() -> dict[str, object]:
    return INFERENCE.model_information()


@app.get("/api/dashboard", response_model=list[StationTelemetry])
def get_dashboard() -> list[dict[str, Any]]:
    return get_analyzed_stations()


@app.get("/api/readings", response_model=StationTelemetry)
def get_readings(station_id: str) -> dict[str, Any]:
    stations = get_analyzed_stations()
    match = next((station for station in stations if station["station_id"].lower() == station_id.lower()), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Station not found in the current feed")
    return match


def _alert_message(station: dict[str, Any], language: str) -> str:
    risk = station["alert"]["risk_level"]
    value = station["current_value"]
    if language == "Sepedi":
        return f"Boemo bja meetse kua {station['name']} ke {value}m. Maemo: {risk}."
    return f"Izinga lamanzi e-{station['name']} lingu-{value}m. Isimo: {risk}."


@app.get("/api/alerts", response_model=list[AlertItem])
def get_alerts() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for station in get_analyzed_stations()[:4]:
        language = "Sepedi" if "A" <= station["station_id"][:1] <= "M" else "isiZulu"
        decision = station["alert"]
        alerts.append(
            {
                "station_id": station["station_id"],
                "language": language,
                "message": _alert_message(station, language),
                "trust_score": station["trust_score"],
                "status": "Review Required" if decision["requires_human_review"] else "Normal",
                "risk_level": decision["risk_level"],
                "reason": decision["reason"],
                "requires_human_review": decision["requires_human_review"],
            }
        )
    return alerts


@app.post("/api/summarize")
def generate_summary(payload: SummaryPayload) -> dict[str, str]:
    """Return a deterministic evidence summary; no language-model claim is made."""
    if payload.status == "healthy" and payload.trust_score >= 70:
        summary = (
            f"Station {payload.station_id} ({payload.name}) has a Trust Score of {payload.trust_score}/100. "
            f"The current stage is {payload.current_value} m and no configured quality anomaly is active."
        )
    else:
        reasons = ", ".join(payload.anomaly_reasons) or "insufficient trusted evidence"
        summary = (
            f"Station {payload.station_id} ({payload.name}) requires review. Trust Score: {payload.trust_score}/100; "
            f"current stage: {payload.current_value} m; evidence: {reasons}."
        )
    return {"summary": summary, "generation_method": "deterministic_template"}


@app.post("/api/feedback")
def post_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    station_id = str(payload.get("station_id") or "UNKNOWN")
    report = str(payload.get("report") or "").strip()
    language = str(payload.get("lang") or "Sepedi")
    if not report:
        raise HTTPException(status_code=422, detail="report is required")
    return {
        "id": generate_local_audit_digest(station_id, datetime.now(timezone.utc).isoformat(), None, 0)[7:19],
        "location": station_id,
        "report": report,
        "lang": language,
        "impact": "Pending independent verification; no Trust Score change has been applied.",
        "message": "Community report received for human review. It has not been merged into a model.",
    }
