import json
from pathlib import Path

import pytest

from trinetra.analytics.crushclock import time_to_danger
from trinetra.analytics.geometry import FloorCalibration, polygon_area
from trinetra.analytics.pipeline import Analyzer
from trinetra.analytics.risk import IncidentTracker, assess_crowd, assess_restricted
from trinetra.mock_scene import MockScene
from trinetra.siteconfig import resolve

ROOT = Path(__file__).resolve().parents[2]
PROFILES = json.loads((ROOT / "config" / "profiles.json").read_text(encoding="utf-8"))
SITE = json.loads((ROOT / "config" / "site.default.json").read_text(encoding="utf-8"))
MOCK_CAM = resolve(next(c for c in SITE["cameras"] if c["source"] == "mock"), MockScene.W, MockScene.H)


def test_calibration_maps_corners_to_metres():
    cal = FloorCalibration([[100, 400], [500, 400], [400, 100], [200, 100]], width_m=4, length_m=6)
    floor = cal.to_floor([[100, 400], [500, 400], [400, 100], [200, 100]])
    assert floor.flatten().tolist() == pytest.approx([0, 0, 4, 0, 4, 6, 0, 6], abs=1e-3)
    assert polygon_area(floor) == pytest.approx(24.0, rel=1e-3)


def test_eta_on_steady_rise():
    samples = [(t, 1.0 + 0.05 * t) for t in range(0, 31)]  # 1.0 -> 2.5 /m^2 over 30 s
    out = time_to_danger(samples, rho_now=2.5, rho_danger=5.0)
    assert out["trend"] == "rising"
    assert out["eta_s"] == pytest.approx(50.0, rel=0.02)  # (5.0 - 2.5) / 0.05


def test_no_eta_when_flat_or_too_short():
    flat = [(t, 3.0) for t in range(0, 31)]
    assert time_to_danger(flat, 3.0, 5.0)["eta_s"] is None
    short = [(t, 1.0 + 0.1 * t) for t in range(0, 5)]
    assert time_to_danger(short, 1.4, 5.0)["trend"] == "warming_up"


def test_far_off_countdown_is_suppressed():
    samples = [(t, 0.10 + 0.001 * t) for t in range(0, 31)]  # +0.001 /m^2/s: about 23 minutes to 1.5
    out = time_to_danger(samples, rho_now=0.13, rho_danger=1.5)
    assert out["eta_s"] is None and out["trend"] == "slow_rise"


def test_crossed_danger_is_high():
    p = PROFILES["station"]
    score, reasons = assess_crowd({"density": 5.2, "eta_s": 0.0, "count": 40, "speed": 0.2,
                                   "surge_ratio": 1.0, "pressure": None, "slope_per_min": None}, p)
    assert score >= 70 and reasons[0]["signal"] in {"density", "eta"}


def test_restricted_intrusion_then_dwell_names_the_people():
    p = PROFILES["station"]
    s1, r1 = assess_restricted({"count": 1, "max_dwell_s": 0, "has_vehicle": False, "ids": [7]}, p, {"dwell_limit_s": 20})
    s2, _ = assess_restricted({"count": 1, "max_dwell_s": 20, "has_vehicle": False}, p, {"dwell_limit_s": 20})
    assert 35 <= s1 < 70 and s2 >= 70
    assert "#7" in r1[0]["text"]


def test_tracker_confirms_merges_and_clears():
    tr = IncidentTracker("cam", confirm_s=1.0, clear_s=5.0, merge_s=60.0)
    ev = []
    for i in range(0, 30):  # 3 s above threshold
        ev += tr.step(i / 10, "z", "Z", "intrusion", 60, [], {})
    assert [e["action"] for e in ev][0] == "opened"
    first_id = ev[0]["incident"]["id"]
    for i in range(30, 100):  # 7 s below -> cleared
        ev += tr.step(i / 10, "z", "Z", "intrusion", 0, [], {})
    assert ev[-1]["action"] == "cleared"
    for i in range(100, 130):  # re-trigger inside the merge window -> same incident
        ev += tr.step(i / 10, "z", "Z", "intrusion", 60, [], {})
    reopened = [e for e in ev if e["action"] == "reopened"]
    assert reopened and reopened[0]["incident"]["id"] == first_id


def test_crush_clock_warns_before_danger_on_synthetic_crowd():
    """Synthetic scene only: proves the plumbing, not real-world accuracy."""
    p = PROFILES["demo"]
    an, scene = Analyzer(MOCK_CAM, p), MockScene(MOCK_CAM)
    opened_at = crossed_at = None
    for i in range(0, 1500):
        t = i / 10
        _, dets = scene.step(t)
        state, events = an.analyze(dets, t)
        z = next(z for z in state["zones"] if z["id"] == "z1")
        if opened_at is None and any(e["incident"]["zone_id"] == "z1" and e["action"] == "opened" for e in events):
            opened_at = t
        if crossed_at is None and z["density"] and z["density"] >= p["density_danger"]:
            crossed_at = t
    assert opened_at is not None and crossed_at is not None
    assert crossed_at - opened_at > 20  # at least 20 s of warning on this scene
