"""
HydroLink edge collector: run on a machine in South Africa (your laptop).

DWS's firewall returns HTTP 403 to overseas cloud IPs, including the LinuxONE
Community Cloud VM. This script scrapes DWS from an SA network and pushes the
rows to the LinuxONE API, which does all the AI.

Windows PowerShell:
    # 1) In one window, open an SSH tunnel (encrypted, no extra port to open):
    ssh -i "C:\\Users\\matom\\Downloads\\hydrolinkSA.pem" -N -L 8000:localhost:8000 linux1@148.100.109.75
    # 2) In another window:
    pip install requests beautifulsoup4
    $env:HYDROLINK_INGEST_TOKEN = "<value from ~/.hydrolink.env on the VM>"
    python collector.py              # every 15 min;  add --once for a single push
"""
import argparse
import os
import platform
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.dws import fetch_unverified  # noqa: E402  (same parser the API uses)


def push(api: str, token: str) -> bool:
    rows, err = fetch_unverified(timeout=30)
    stamp = datetime.now().strftime("%H:%M:%S")
    if not rows:
        print(f"[{stamp}] DWS fetch failed: {err}")
        return False
    newest = max((r["timestamp"] or "") for r in rows)
    try:
        r = requests.post(f"{api}/api/ingest", timeout=120,
                          headers={"X-HydroLink-Token": token},
                          json={"collector": f"edge@{platform.node()}", "rows": rows})
        r.raise_for_status()
        print(f"[{stamp}] pushed {len(rows)} stations (newest DWS reading {newest}) -> {r.json()}")
        return True
    except Exception as e:
        print(f"[{stamp}] push to {api} failed: {e}")
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.getenv("HYDROLINK_API", "http://localhost:8000"))
    ap.add_argument("--interval", type=int, default=900, help="seconds between pushes")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    token = os.getenv("HYDROLINK_INGEST_TOKEN")
    if not token:
        sys.exit("Set HYDROLINK_INGEST_TOKEN (copy it from ~/.hydrolink.env on the VM).")
    if a.once:
        sys.exit(0 if push(a.api, token) else 1)
    while True:
        push(a.api, token)
        time.sleep(a.interval)
