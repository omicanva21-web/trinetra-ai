"""Print every camera's zones and counting lines with the floor area Trinetra computes, to check calibration.

  python backend/tools/check_zones.py            (run from the project folder)

Compare each area with reality (tape measure or floor tiles). More than about 20% off: re-click the points.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from trinetra.analytics.pipeline import Analyzer  # noqa: E402
from trinetra.siteconfig import resolve  # noqa: E402

site = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
profiles = json.loads((ROOT / "config" / "profiles.json").read_text(encoding="utf-8"))
profile = profiles[site.get("profile", "station")]

for cam in site["cameras"]:
    an = Analyzer(resolve(cam, 1000, 1000), profile)  # areas do not depend on the resolution used here
    calib = "calibrated" if an.calib is not None else "NOT calibrated (crowd zones need area_m2)"
    print(f"{cam['id']}  {cam.get('name', '')}  source={cam['source']}  {calib}")
    for z in an.zones:
        if z.area_m2:
            area = f"{z.area_m2:.1f} m²"
        else:
            area = "not needed (restricted zone)" if z.kind == "restricted" else "UNKNOWN: add calibration or area_m2"
        print(f"   {z.id:<4} {z.kind:<10} {z.name:<20} area {area}")
    for ln in cam.get("lines", []):
        print(f"   {ln['id']:<4} {'line':<10} {ln['name']:<20} {ln['points_norm']}")
