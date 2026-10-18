"""
DWS Unverified page: fetch + parse. Shared by the API (direct mode) and by
collector.py (edge mode, run from a South African network, because DWS's
firewall returns 403 to overseas cloud IPs such as the LinuxONE Community Cloud).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

DWS_URL = "https://www.dws.gov.za/Hydrology/Unverified"
HEADERS = {"User-Agent": "HydroLinkSA/5 (IBM Z Datathon; public hydrology data)"}


def _num(text: str) -> Optional[float]:
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None


def parse_unverified(html: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for tr in BeautifulSoup(html, "html.parser").find_all("tr"):
        cols = [c.text.strip() for c in tr.find_all("td")]
        if len(cols) >= 4 and len(cols[0]) >= 5:
            stage = _num(cols[3])
            if stage is None:
                continue
            rows.append({"station_id": cols[0], "name": cols[1], "timestamp": cols[2] or None,
                         "stage": stage, "flow_cap": _num(cols[4]) if len(cols) > 4 else None})
    return rows


def fetch_unverified(timeout: float = 30) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Returns (rows, error). Non-200 responses are errors too (the old code
    skipped them silently, which is why a 403 never showed up in the logs)."""
    try:
        r = requests.get(DWS_URL, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return [], f"HTTP {r.status_code} from DWS ({len(r.text)} bytes)"
        rows = parse_unverified(r.text)
        return rows, None if rows else "HTTP 200 but no station rows parsed"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
