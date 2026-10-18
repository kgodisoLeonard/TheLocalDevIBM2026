"""
Run on the LinuxONE VM BEFORE training, to prove every data source works:

    docker exec hydrolink-api python verify_sources.py          # inside the API container
    # or: HYDROLINK_SHARED_DIR=~/shared python3 verify_sources.py

Prints PASS/FAIL per source with row counts and sample values. Exits 1 if
GloFAS or rainfall (the sources the live AI depends on) fail.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend import sources as S  # noqa: E402

LAT, LON = float(os.getenv("TEST_LAT", "-26.92")), float(os.getenv("TEST_LON", "29.29"))
today = date.today()
results = {}


def check(name, fn, critical=False):
    try:
        out = fn()
        ok = bool(out)
        sample = list(out.items())[-3:] if isinstance(out, dict) else out
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {len(out) if hasattr(out, '__len__') else ''} rows  {sample}")
    except Exception as e:
        ok = False
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")
    results[name] = (ok, critical)


check("GloFAS recent (flood-api.open-meteo.com)", lambda: S.glofas_recent(LAT, LON), critical=True)
check("GloFAS history 2024", lambda: S.glofas_history(LAT, LON, "2024-01-01", "2024-12-31"))
check("Rain recent (api.open-meteo.com)", lambda: S.rain_recent(LAT, LON), critical=True)
check("Rain history ERA5 (archive-api.open-meteo.com)",
      lambda: S.rain_history(LAT, LON, (today - timedelta(days=40)).isoformat(),
                             (today - timedelta(days=10)).isoformat()))
check("Station registry (seed + shared/stations.json)", S.load_stations)
check("GRDC files in shared/history/grdc/", lambda: {k: len(v[1]) for k, v in S.load_grdc_dir().items()})
if os.getenv("USE_DWS_VERIFIED") == "1":
    check("DWS Verified (EXPERIMENTAL url pattern)",
          lambda: S.dws_verified_daily(os.getenv("TEST_STATION", "C1H006"), "2024-01-01", "2024-03-31"))
else:
    print("[SKIP] DWS Verified: set USE_DWS_VERIFIED=1 (and DWS_VERIFIED_URL once checked in a browser)")

failed_critical = [n for n, (ok, crit) in results.items() if crit and not ok]
print("\nCRITICAL FAILURES:" if failed_critical else "\nAll critical sources OK.", *failed_critical)
sys.exit(1 if failed_critical else 0)
