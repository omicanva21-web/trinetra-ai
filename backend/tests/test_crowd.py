"""Dense-crowd mode: camera-motion compensation, tracker switches for seated crowds, tiled detector."""
import cv2
import numpy as np
import pytest
from conftest import ROOT  # noqa: F401  (temporary site created before any trinetra import)

from trinetra.analytics.tracks import TrackRegistry  # noqa: E402
from trinetra.tracking import ByteTrackLite, CameraMotion  # noqa: E402


def person(x, y, conf=0.8, w=30, h=60):
    return {"id": None, "cls": "person", "box": [x, y, x + w, y + h], "conf": conf}


def test_defaults_unchanged_for_live_cameras():
    t = ByteTrackLite()
    assert t.rescue is True and t.predict_s == 1.0 and t.static_after_s == 4.0


def test_camera_pan_keeps_ids_with_compensation():
    """Ten seated people; the camera pans 40 px between frames. Without compensation the boxes no longer
    overlap and everyone gets a new ID; with it, every ID survives."""
    people = [(60 + 70 * i, 200) for i in range(10)]
    for compensate, expect_same in ((False, False), (True, True)):
        tr = ByteTrackLite(high=0.3, iou_high=0.15, rescue=False, predict_s=0.0, static_after_s=1e9)
        for k in range(3):
            out = tr.update([person(x, y) for x, y in people], k / 3)
        first = {o["id"] for o in out}
        assert None not in first and len(first) == 10
        m = np.array([[1.0, 0, 40.0], [0, 1.0, 0]])
        if compensate:
            tr.compensate(m)
        out = tr.update([person(x + 40, y) for x, y in people], 1.0)
        assert ({o["id"] for o in out} == first) is expect_same


def test_no_rescue_never_hands_an_id_to_a_neighbour():
    """A lost person must not take over someone else nearby (packed rooms)."""
    for rescue in (True, False):
        tr = ByteTrackLite(rescue=rescue, predict_s=0.0, static_after_s=1e9)
        for k in range(3):
            out = tr.update([person(100, 100)], k / 3)
        tid = out[0]["id"]
        out = tr.update([person(140, 100)], 1.0)  # someone else right next to them, boxes do not overlap
        took_over = out[0]["id"] == tid
        assert took_over is rescue


def test_seated_people_are_not_dropped_as_static_objects():
    from trinetra.detector import CrowdDetector

    tr = ByteTrackLite(**CrowdDetector.TRACKER_ARGS)  # the dense-crowd settings
    for k in range(40):  # 13 s of a still, weakly detected person
        out = tr.update([person(200, 150, conf=0.42 if k == 0 else 0.33)], k / 3)
    assert out[0]["id"] == 1 and "demoted" not in out[0]


def test_camera_motion_estimate():
    rng = np.random.default_rng(0)
    img = (rng.random((480, 854)) * 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 3)
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    shifted = cv2.warpAffine(img, np.float32([[1, 0, 12], [0, 1, -7]]), (854, 480), borderMode=cv2.BORDER_REFLECT)
    cm = CameraMotion()
    assert cm.estimate(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)) is None  # first frame
    m = cm.estimate(cv2.cvtColor(shifted, cv2.COLOR_GRAY2BGR))
    assert m is not None and abs(m[0, 2] - 12) < 1.5 and abs(m[1, 2] + 7) < 1.5
    assert cm.estimate(cv2.cvtColor(shifted, cv2.COLOR_GRAY2BGR)) is None  # still camera


def test_registry_without_speed_estimate():
    reg = TrackRegistry((854, 480), None, [], [], estimate_speed=False)
    for k in range(10):
        reg.update(k / 3, 0.0, [{**person(100 + 20 * k, 100), "id": 1, "foot": (115 + 20 * k, 160)}])
    row = reg.snapshot()["active"][0]
    assert row["speed"] is None and row["dist"] is None


def test_crowd_detector_finds_tiny_people():
    """People 17-28 px tall in an 854x480 frame (like a hall filmed from a balcony): Dense crowd finds all 7 people
    the model sees at full size; Fast (NanoDet) misses several. (At full size NanoDet also boxes traffic cones.)"""
    from trinetra.detector import CrowdDetector, NanodetDetector, make_detector

    try:
        crowd = CrowdDetector()
    except Exception as exc:
        pytest.skip(f"model unavailable: {exc}")
    clip = ROOT / "clips" / "vtest.avi"
    if not clip.exists():
        pytest.skip("sample clip missing")
    cap = cv2.VideoCapture(str(clip))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 200)
    ok, frame = cap.read()
    cap.release()
    tiny = cv2.copyMakeBorder(cv2.resize(frame, (256, 192)), 144, 144, 299, 299, cv2.BORDER_REPLICATE)  # 854 x 480
    people = lambda dets: [d for d in dets if d["cls"] == "person" and d["conf"] >= 0.3]  # noqa: E731
    reference = len(people(crowd._infer(frame)))  # the same people at full size
    found = people(crowd.raw_detect(tiny))
    fast = people(NanodetDetector().raw_detect(tiny))
    assert reference >= 6 and len(found) >= reference - 1 and len(found) >= len(fast) + 2
    assert all(d["box"][3] - d["box"][1] < 60 for d in found)  # boxes are the tiny people, not the whole scene
    assert crowd.grid(854, 480) == (5, 4) and crowd.grid(384, 288) == (2, 2)
    det, err = make_detector("auto", "crowd")
    assert err is None and "dense crowd" in det.name
    assert det.tracker.rescue is False and det.tracker.static_after_s > 1e6
