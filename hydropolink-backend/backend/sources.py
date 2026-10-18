"""
External data sources for HydroLink, behind one cached, failure-tolerant layer.

  GloFAS river discharge   Open-Meteo Flood API     modelled, daily, 1984 -> +7 months
  Rainfall (recent)        Open-Meteo Forecast API  past_days, no delay
  Rainfall (history)       Open-Meteo Archive API   ERA5, about 5 days behind
  GRDC gauge history       files you download from the GRDC portal -> shared/history/grdc/
  DWS Verified daily       EXPERIMENTAL scrape, URL pattern set by env (verify first)
  Station registry         shared/stations.json (lat/lon) + coordinates from GRDC headers

Every HTTP call is cached on the shared volume (shared/cache). If a source is
down, the last good copy is used; if there is none, the caller gets {} and the
model treats that input as neutral. A source outage never breaks the API.
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import re
import time
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

import requests

SHARED_DIR = os.getenv("HYDROLINK_SHARED_DIR", "/shared")
CACHE_DIR = os.path.join(SHARED_DIR, "cache")
UA = {"User-Agent": "HydroLinkSA/5 (IBM Z Datathon; non-commercial)"}

FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# Unverified pattern: open a station in the DWS Verified site in your browser,
# copy the data URL, and set DWS_VERIFIED_URL with {station} {start} {end} {site}.
DWS_VERIFIED_URL = os.getenv(
    "DWS_VERIFIED_URL",
    "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx?Station={station}100.00"
    "&DataType=Daily&StartDT={start}&EndDT={end}&SiteType={site}")

LIVE_TTL = 3 * 3600          # recent rain / discharge: refresh every 3 h
HISTORY_TTL = 30 * 24 * 3600  # history barely changes


# --------------------------------------------------------------------------- cache
def _cache_path(url: str, params: dict) -> str:
    key = hashlib.sha1((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    return os.path.join(CACHE_DIR, key + ".json")


def _get_json(url: str, params: dict, ttl: int, timeout: float = 8.0) -> Optional[dict]:
    path = _cache_path(url, params)
    cached = None
    if os.path.exists(path):
        try:
            cached = json.load(open(path))
            if time.time() - cached["_fetched_at"] < ttl:
                return cached["data"]
        except Exception:
            cached = None
    try:
        r = requests.get(url, params=params, headers=UA, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            raise ValueError(data.get("reason", "api error"))
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        json.dump({"_fetched_at": time.time(), "url": url, "params": params, "data": data}, open(tmp, "w"))
        os.replace(tmp, path)
        return data
    except Exception as e:
        print(f"[sources] {url.split('/')[2]} failed ({e}); {'using stale cache' if cached else 'no cache'}")
        return cached["data"] if cached else None


def _daily(data: Optional[dict], var: str) -> Dict[str, float]:
    if not data or "daily" not in data:
        return {}
    d = data["daily"]
    return {t: float(v) for t, v in zip(d.get("time", []), d.get(var, [])) if v is not None}


# --------------------------------------------------------------------------- GloFAS
def glofas_history(lat: float, lon: float, start: str, end: str) -> Dict[str, float]:
    """Daily modelled river discharge (m3/s), date -> value."""
    return _daily(_get_json(FLOOD_URL, {"latitude": lat, "longitude": lon, "daily": "river_discharge",
                                        "start_date": start, "end_date": end}, HISTORY_TTL, 30),
                  "river_discharge")


def glofas_recent(lat: float, lon: float, past_days: int = 7, forecast_days: int = 7) -> Dict[str, float]:
    return _daily(_get_json(FLOOD_URL, {"latitude": lat, "longitude": lon, "daily": "river_discharge",
                                        "past_days": past_days, "forecast_days": forecast_days}, LIVE_TTL),
                  "river_discharge")


# --------------------------------------------------------------------------- rainfall
def rain_history(lat: float, lon: float, start: str, end: str) -> Dict[str, float]:
    """Daily precipitation (mm) from ERA5 reanalysis, about 5 days behind real time."""
    return _daily(_get_json(ARCHIVE_URL, {"latitude": lat, "longitude": lon, "daily": "precipitation_sum",
                                          "start_date": start, "end_date": end,
                                          "timezone": "Africa/Johannesburg"}, HISTORY_TTL, 30),
                  "precipitation_sum")


def rain_recent(lat: float, lon: float, past_days: int = 7) -> Dict[str, float]:
    return _daily(_get_json(FORECAST_URL, {"latitude": lat, "longitude": lon, "daily": "precipitation_sum",
                                           "past_days": past_days, "forecast_days": 1,
                                           "timezone": "Africa/Johannesburg"}, LIVE_TTL),
                  "precipitation_sum")


def rain_3day(rain: Dict[str, float], day: str) -> Optional[float]:
    """Sum of rain on `day` and the two days before; None if no data at all."""
    d = date.fromisoformat(day)
    vals = [rain.get((d - timedelta(days=i)).isoformat()) for i in range(3)]
    vals = [v for v in vals if v is not None]
    return float(sum(vals)) if vals else None


# --------------------------------------------------------------------------- GRDC
_GRDC_META = {"grdc-no.": "grdc_no", "river": "river", "station": "station",
              "country": "country", "latitude (dd)": "lat", "longitude (dd)": "lon",
              "catchment area (km²)": "area_km2", "catchment area (km2)": "area_km2"}


def parse_grdc(path: str) -> Tuple[dict, Dict[str, float]]:
    """Parse a GRDC daily export ('# key: value' header, then
    'YYYY-MM-DD;hh:mm; Value' rows; -999 = missing). Tolerant of variants."""
    meta: dict = {"file": os.path.basename(path)}
    values: Dict[str, float] = {}
    row = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*;[^;]*;\s*(-?\d+(?:\.\d+)?)")
    with open(path, encoding="latin-1") as f:
        for line in f:
            if line.startswith("#"):
                if ":" in line:
                    k, v = line[1:].split(":", 1)
                    k = k.strip().lower()
                    if k in _GRDC_META:
                        meta[_GRDC_META[k]] = v.strip()
                continue
            m = row.match(line)
            if m:
                v = float(m.group(2))
                if v > -998:
                    values[m.group(1)] = v
    for k in ("lat", "lon"):
        try:
            meta[k] = float(meta[k])
        except (KeyError, ValueError):
            meta.pop(k, None)
    return meta, values


def load_grdc_dir(directory: Optional[str] = None) -> Dict[str, Tuple[dict, Dict[str, float]]]:
    directory = directory or os.path.join(SHARED_DIR, "history", "grdc")
    out = {}
    for p in sorted(glob.glob(os.path.join(directory, "*.txt")) + glob.glob(os.path.join(directory, "*.csv"))):
        try:
            meta, vals = parse_grdc(p)
            if vals:
                out[f"GRDC{meta.get('grdc_no', os.path.basename(p).split('_')[0])}"] = (meta, vals)
        except Exception as e:
            print(f"[sources] GRDC parse failed {p}: {e}")
    return out


# --------------------------------------------------------------------------- DWS Verified
def dws_verified_daily(station: str, start: str, end: str, site: str = "RIV") -> Dict[str, float]:
    """EXPERIMENTAL. Pulls the first numeric column after a date on each line
    of the DWS Verified data page. Run verify_sources.py before trusting it."""
    from bs4 import BeautifulSoup
    url = DWS_VERIFIED_URL.format(station=station, start=start, end=end, site=site)
    path = _cache_path(url, {})
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < HISTORY_TTL:
            text = json.load(open(path))["text"]
        else:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            text = BeautifulSoup(r.text, "html.parser").get_text("\n")
            os.makedirs(CACHE_DIR, exist_ok=True)
            json.dump({"text": text, "url": url}, open(path, "w"))
    except Exception as e:
        print(f"[sources] DWS verified failed for {station}: {e}")
        return {}
    out = {}
    pat = re.compile(r"^\s*(\d{4})[-/]?(\d{2})[-/]?(\d{2})\s+(-?\d+(?:\.\d+)?)")
    for line in text.splitlines():
        m = pat.match(line)
        if m:
            v = float(m.group(4))
            if v >= 0:
                out[f"{m.group(1)}-{m.group(2)}-{m.group(3)}"] = v
    return out


# --------------------------------------------------------------------------- stations
# Coordinates must come from the DWS Station Catalogue or GRDC metadata.
# Seeds marked approx=True are rough and only good enough for rainfall.
SEED_STATIONS: Dict[str, dict] = {
    "C1R002": {"name": "Vaal at Grootdraai Dam", "lat": -26.92, "lon": 29.29, "approx": True},
}


def _km(a_lat, a_lon, b_lat, b_lon) -> float:
    p = math.pi / 180
    h = (math.sin((b_lat - a_lat) * p / 2) ** 2 +
         math.cos(a_lat * p) * math.cos(b_lat * p) * math.sin((b_lon - a_lon) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def load_stations() -> Dict[str, dict]:
    """Seed < shared/stations.json (your verified coordinates win)."""
    reg = {k: dict(v) for k, v in SEED_STATIONS.items()}
    path = os.path.join(SHARED_DIR, "stations.json")
    if os.path.exists(path):
        try:
            for sid, v in json.load(open(path)).items():
                reg.setdefault(sid, {}).update(v)
                reg[sid].setdefault("approx", False)
        except Exception as e:
            print(f"[sources] stations.json unreadable: {e}")
    return {k: v for k, v in reg.items() if "lat" in v and "lon" in v}


def match_grdc_to_station(meta: dict, stations: Dict[str, dict], max_km: float = 3.0) -> Optional[str]:
    if "lat" not in meta:
        return None
    best = min(((_km(meta["lat"], meta["lon"], s["lat"], s["lon"]), sid) for sid, s in stations.items()
                if not s.get("approx")), default=None)
    return best[1] if best and best[0] <= max_km else None
