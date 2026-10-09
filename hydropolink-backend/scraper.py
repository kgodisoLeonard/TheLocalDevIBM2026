"""DWS near-real-time ingestion with provenance preserved."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup


LOGGER = logging.getLogger(__name__)
DWS_UNVERIFIED_URL = "https://www.dws.gov.za/Hydrology/Unverified/"
SAST = timezone(timedelta(hours=2))


def _parse_number(text: str) -> float | None:
    cleaned = text.strip().replace(",", "")
    if not cleaned or cleaned in {"-", "--", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_dws_timestamp(text: str) -> datetime | None:
    cleaned = " ".join(text.split())
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=SAST).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def parse_dws_station_table(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    stations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in soup.find_all("tr"):
        columns = [column.get_text(" ", strip=True) for column in row.find_all("td")]
        if len(columns) < 4:
            continue
        station_id = columns[0].strip().upper()
        if len(station_id) < 5 or not any(character.isdigit() for character in station_id):
            continue
        timestamp = _parse_dws_timestamp(columns[2])
        stage = _parse_number(columns[3])
        if timestamp is None or stage is None:
            continue
        key = (station_id, timestamp.isoformat())
        if key in seen:
            continue
        seen.add(key)
        stations.append(
            {
                "station_id": station_id,
                "name": columns[1] or station_id,
                "timestamp": timestamp.isoformat(),
                "current_value": stage,
                "flow_or_capacity": _parse_number(columns[4]) if len(columns) > 4 else None,
                "source": "dws_unverified_near_real_time",
                "source_url": DWS_UNVERIFIED_URL,
            }
        )
    return stations


def fetch_live_dws_stations(timeout_seconds: float = 12.0) -> list[dict[str, Any]]:
    response = requests.get(
        DWS_UNVERIFIED_URL,
        headers={"User-Agent": "HydroLink-SA/1.0 (+IBM-Z-Datathon-2026)"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    stations = parse_dws_station_table(response.text)
    if not stations:
        raise ValueError("DWS response contained no parseable station readings")
    return stations


def fetch_live_dws_station_data(station_code: str = "C1H019") -> dict[str, Any]:
    """Backward-compatible single-station helper with an explicit fallback."""
    try:
        stations = fetch_live_dws_stations()
        match = next((item for item in stations if item["station_id"] == station_code.upper()), None)
        if match is not None:
            return match
    except (requests.RequestException, ValueError) as exc:
        LOGGER.warning("DWS feed unavailable: %s", exc)
    now = datetime.now(timezone.utc)
    return {
        "station_id": station_code.upper(),
        "name": "Grootdraai Dam Outflow (development fallback)",
        "timestamp": now.isoformat(),
        "current_value": 0.843,
        "flow_or_capacity": None,
        "source": "synthetic_fallback_not_dws",
        "source_url": None,
    }
