"""API tests against a temporary site with a simulated camera and a browser camera (no webcam or model)."""
import json
import time

import cv2
import numpy as np
from conftest import TMP  # noqa: E402  (temporary site created before any trinetra import)

from fastapi.testclient import TestClient  # noqa: E402

from trinetra.main import app, store  # noqa: E402

SQUARE = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]]


def wait_for(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        out = fn()
        if out:
            return out
        time.sleep(0.2)
    return None


def test_full_api():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"] is True
        cfg = client.get("/api/config").json()
        cam_id = cfg["cameras"][0]["id"]

        # live frame, metrics and stats appear once the simulated camera runs
        assert wait_for(lambda: client.get(f"/api/cameras/{cam_id}/frame.jpg").status_code == 200)
        assert wait_for(lambda: client.get("/api/metrics?minutes=5").json().get(cam_id), timeout=6)
        s = client.get("/api/stats").json()
        assert s["live"]["cameras_running"] >= 1 and "by_level" in s and len(s["timeline"]) == 12

        # zones and lines come back normalised for the Setup page
        cams = client.get("/api/cameras").json()
        assert all("polygon_norm" in z for z in cams[0]["zones"]) and cams[0]["lines"][0]["points_norm"]

        # add, edit and delete a camera
        body = {"name": "Test clip", "source": "clips/does-not-exist.mp4", "enabled": True,
                "zones": [{"name": "Gate", "kind": "restricted", "polygon_norm": SQUARE}],
                "lines": [{"name": "Door", "points_norm": [[0.5, 1], [0.5, 0]]}], "options": {"max_fps": 5}}
        new = client.post("/api/cameras", json=body).json()
        assert new["id"] not in ("cam3", "cam4", "cam9") and new["zones"][0]["id"] == "z1" and new["lines"][0]["id"] == "l1"
        assert wait_for(lambda: "not found" in [c for c in client.get("/api/cameras").json() if c["id"] == new["id"]][0]["status"])
        body["enabled"] = False
        assert client.put(f"/api/cameras/{new['id']}", json=body).json()["status"] == "disabled"
        bad = dict(body, zones=[{"name": "x", "kind": "crowd", "polygon_norm": [[0, 0], [2, 0], [0, 1]]}])
        assert client.put(f"/api/cameras/{new['id']}", json=bad).status_code == 422
        assert client.delete(f"/api/cameras/{new['id']}").json()["deleted"] == new["id"]
        saved = json.loads((TMP / "site.json").read_text(encoding="utf-8"))
        assert {c["id"] for c in saved["cameras"]} == {"cam3", "cam4", "cam9"}

        # thresholds: valid edit saved, invalid rejected
        prof = client.get("/api/profiles").json()["profiles"]["demo"]
        prof["density_danger"] = 1.6
        assert client.put("/api/profiles/demo", json=prof).json()["density_danger"] == 1.6
        assert client.put("/api/profiles/demo", json=dict(prof, density_warn=3.0)).status_code == 422
        assert client.post("/api/profile", json={"name": "station"}).json()["profile"] == "station"

        # incidents and operator actions
        store.upsert_from_event({"action": "opened", "incident": {
            "id": "test0001", "camera_id": cam_id, "zone_id": "z2", "zone_name": "Track edge",
            "kind": "intrusion", "level": "MEDIUM", "score": 55, "reasons": [], "metrics": {}}}, time.time() - 30)
        r = client.post("/api/incidents/test0001/action", json={"action": "dispatch", "note": "Team B sent"})
        assert r.status_code == 200 and r.json()["status"] == "dispatched"
        assert client.post("/api/incidents/test0001/action", json={"action": "explode"}).status_code == 422
        assert client.get("/api/incidents/test0001").json()["actions"][0]["note"] == "Team B sent"
        assert client.get("/api/incidents?level=MEDIUM").json()[0]["id"] == "test0001"
        assert client.get("/api/stats").json()["avg_response_s"] >= 29
        assert client.get("/api/incidents/nope/snapshot").status_code == 404

        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"


def test_tracking_endpoints_and_browser_camera():
    with TestClient(app) as client:
        # the simulated camera produces tracks with paths
        tracks = wait_for(lambda: (lambda j: j if j["active"] else None)(client.get("/api/cameras/cam3/tracks").json()))
        assert tracks and tracks["active"][0]["path"] and tracks["summary"]["active_count"] >= 1
        tid = tracks["active"][0]["id"]
        assert client.post("/api/cameras/cam3/focus", json={"track_id": tid}).json()["focus"] == tid
        assert client.post("/api/cameras/cam3/focus", json={"track_id": None}).json()["focus"] is None
        st = client.get("/api/tracking/stats?camera_id=cam3&window_min=30").json()
        assert len(st["timeline"]) == 30 and len(st["dwell_hist"]) == 6

        # a non-browser camera refuses frames; the browser camera accepts them
        try:
            with client.websocket_connect("/ws/camera/cam3") as bad:
                bad.send_bytes(b"x")
                bad.receive_text()
            refused = False
        except Exception:
            refused = True
        assert refused
        assert "waiting" in wait_for(lambda: [c for c in client.get("/api/cameras").json() if c["id"] == "cam9"][0]["status"]
                                     if "waiting" in [c for c in client.get("/api/cameras").json() if c["id"] == "cam9"][0]["status"] else None)
        img = np.full((360, 640, 3), 90, np.uint8)
        jpeg = cv2.imencode(".jpg", img)[1].tobytes()
        with client.websocket_connect("/ws/camera/cam9") as cam:
            for _ in range(10):
                cam.send_bytes(jpeg)
                time.sleep(0.1)
            assert wait_for(lambda: client.get("/api/cameras/cam9/frame.jpg").status_code == 200)
            view = [c for c in client.get("/api/cameras").json() if c["id"] == "cam9"][0]
            assert view["size"] == [640, 360] and view["browser_connected"] is True
