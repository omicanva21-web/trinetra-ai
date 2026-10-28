"""Camera 4 (uploaded video): upload checks, playback controls, video timeline, incidents, cleanup.

The API tests run with the detector off (fast, no model); test_real_tracking_on_uploaded_video runs the
bundled NanoDet + ByteTrack-lite on a real pedestrian clip through the same reader the worker uses.
"""
import re
import threading
import time
from urllib.parse import quote

import cv2
import pytest
from conftest import ROOT, TMP  # noqa: E402  (temporary site created before any trinetra import)

from fastapi.testclient import TestClient  # noqa: E402

from trinetra import uploads  # noqa: E402
from trinetra.main import app, store  # noqa: E402

CLIP = ROOT / "clips" / "vtest.avi"
needs_clip = pytest.mark.skipif(not CLIP.exists(), reason="clips/vtest.avi missing (start.bat downloads it)")


def make_mp4(path, seconds=6.0, fps=10, start=0):
    cap = cv2.VideoCapture(str(CLIP))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for _ in range(int(seconds * fps)):
        ok, frame = cap.read()
        if not ok:
            break
        out.write(frame)
    out.release()
    cap.release()
    return path


def upload(client, data: bytes, name="clip.mp4"):
    return client.post("/api/cameras/cam4/video", content=data,
                       headers={"X-Filename": quote(name), "Content-Type": "application/octet-stream"})


def control(client, action, **kw):
    return client.post("/api/cameras/cam4/video/control", json={"action": action, **kw})


def wait_video(client, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get("/api/cameras/cam4/video").json()
        if cond(v):
            return v
        time.sleep(0.1)
    raise AssertionError(f"timed out; last state {v}")


def test_sniff_container():
    assert uploads.sniff_container(b"\0\0\0\x18ftypisom" + b"\0" * 8) == "mp4"
    assert uploads.sniff_container(b"\0\0\0\x14ftypqt  " + b"\0" * 8) == "mov"
    assert uploads.sniff_container(b"RIFF\0\0\0\0AVI LIST") == "avi"
    assert uploads.sniff_container(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x84webm") == "webm"
    assert uploads.sniff_container(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x88matroska") == "mkv"
    assert uploads.sniff_container(b"# README\nhello") is None
    assert uploads.clean_display_name("..\\..\\C:\\secret\\My clip.mp4") == "My clip.mp4"
    assert uploads.clean_display_name("") == "video"


@needs_clip
def test_upload_rejects_bad_files(tmp_path):
    with TestClient(app) as client:
        assert client.get("/api/cameras/cam4/video").json()["state"] == "empty"
        r = upload(client, b"")
        assert r.status_code == 400 and "empty" in r.json()["detail"]
        r = upload(client, b"just text, renamed to look like a video " * 20, "notes.mp4")
        assert r.status_code == 415 and "Accepted formats" in r.json()["detail"]
        good = make_mp4(tmp_path / "x.mp4", seconds=3).read_bytes()
        r = upload(client, good[:3000], "cut.mp4")  # real header, missing data
        assert r.status_code == 415
        r = upload(client, good[:12] + b"\0" * (6 * 1024 * 1024), "huge.mp4")  # limit is 5 MB in tests
        assert r.status_code == 413 and "MB" in r.json()["detail"]
        assert client.post("/api/cameras/cam3/video", content=good).status_code == 400  # not an upload camera
        assert control(client, "start").status_code == 409  # nothing uploaded
        assert not list((TMP / "uploads" / "incoming").glob("*.part"))  # rejected uploads are deleted
        assert client.get("/api/cameras/cam4/video").json()["state"] == "empty"


@needs_clip
def test_upload_controls_and_cleanup(tmp_path):
    mp4 = make_mp4(tmp_path / "walk.mp4", seconds=8)
    with TestClient(app) as client:
        r = upload(client, mp4.read_bytes(), "../../etc/My walk.mp4")
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["state"] == "ready" and v["file"] == "My walk.mp4" and v["container"] == "mp4"
        assert 7.5 <= v["duration_s"] <= 8.5 and v["video_fps"] == 10
        files = sorted(p.name for p in (TMP / "uploads" / "cam4").iterdir())
        assert files[1] == "meta.json" and re.fullmatch(r"[0-9a-f]{32}\.mp4", files[0])  # server-made name
        assert wait_video(client, lambda x: x["state"] == "ready")
        assert client.get("/api/cameras/cam4/frame.jpg").status_code == 200  # first frame, for drawing zones

        assert control(client, "pause").status_code == 409
        v = control(client, "start").json()
        assert v["state"] == "processing" and v["session"]
        first_session = v["session"]
        v = wait_video(client, lambda x: x["position_s"] >= 1.0)
        assert control(client, "start").json()["state"] == "processing"  # no second loop
        assert sum(1 for t in threading.enumerate() if t.name == "cam-cam4" and t.is_alive()) == 1
        assert upload(client, mp4.read_bytes()).status_code == 409  # must stop first

        v = control(client, "pause").json()
        assert v["state"] == "paused"
        paused_at = v["position_s"]
        time.sleep(1.0)
        assert client.get("/api/cameras/cam4/video").json()["position_s"] == paused_at
        assert control(client, "resume").json()["state"] == "processing"
        wait_video(client, lambda x: x["position_s"] > paused_at + 0.5)

        v = control(client, "restart").json()
        assert v["state"] == "processing" and v["session"] != first_session and v["position_s"] < 1.0
        v = control(client, "stop").json()
        assert v["state"] == "stopped"
        assert control(client, "stop").status_code == 409

        assert control(client, "speed", speed=3).status_code == 409  # not one of the offered speeds
        assert control(client, "speed", speed=0).json()["speed"] == 0  # as fast as possible
        assert control(client, "start").json()["state"] == "processing"
        v = wait_video(client, lambda x: x["state"] == "completed", timeout=30)
        assert v["progress"] == 1.0 and v["position_s"] >= 7.0 and v["frames_analysed"] >= 70

        tl = client.get("/api/cameras/cam4/video/timeline").json()
        vts = [s["vt"] for s in tl["samples"]]
        assert tl["session"] == v["session"] and len(vts) >= 7 and vts == sorted(vts)
        assert len(v["video_id"]) == 32 and v["video_id"] != files[0][:32]  # content fingerprint, not the file name
        st = client.get("/api/tracking/stats?camera_id=cam4").json()
        assert st["axis"] == "video" and st["session"] == v["session"]
        s = client.get("/api/stats?scope=video&camera_id=cam4").json()
        assert "by_level" in s
        assert client.get("/api/stats?scope=live").json()["live"]["uploaded_videos"] == 1

        v = client.delete("/api/cameras/cam4/video").json()
        assert v["state"] == "empty" and v["file"] is None
        assert not (TMP / "uploads" / "cam4").exists()
        assert control(client, "start").status_code == 409


def test_incident_video_fields_and_dedup():
    """An incident from a video keeps its time in the video; a re-run of the same moment is recognised."""
    ev = {"action": "opened", "incident": {"id": "vid00001", "camera_id": "cam4", "zone_id": "z9", "zone_name": "Gate",
                                           "kind": "intrusion", "level": "MEDIUM", "score": 60, "started_at": 83.2}}
    row = store.upsert_from_event(ev, time.time(), {"source_kind": "upload", "video_id": "abc", "video_name": "gate.mp4",
                                                     "video_ts": 83.2})
    assert row["video_ts"] == 83.2 and row["source_kind"] == "upload" and row["video_name"] == "gate.mp4"
    ev["action"], ev["incident"]["level"] = "updated", "HIGH"
    row = store.upsert_from_event(ev, time.time(), {"source_kind": "upload", "video_id": "abc", "video_ts": 83.2, "video_end": 97.5})
    assert row["video_end"] == 97.5 and row["video_ts"] == 83.2 and row["level"] == "HIGH"
    assert store.find_video_incident("cam4", "abc", "z9", 85.0)["id"] == "vid00001"
    assert store.find_video_incident("cam4", "abc", "z9", 120.0) is None
    assert store.find_video_incident("cam4", "other", "z9", 83.2) is None
    live = store.stats(scope="live")
    video = store.stats(scope="video", camera_id="cam4", video_id="abc")
    assert video["total"] == 1 and live["total"] == store.stats()["total"] - 1


@needs_clip
def test_real_tracking_on_uploaded_video(tmp_path):
    """The same reader + detector + tracker the worker uses, on real pedestrians: stable IDs, video-time clock."""
    from trinetra.analytics.tracks import TrackRegistry
    from trinetra.detector import NanodetDetector

    try:
        det = NanodetDetector()
    except Exception as exc:  # model file missing and no internet
        pytest.skip(f"NanoDet model unavailable: {exc}")
    mp4 = make_mp4(tmp_path / "people.mp4", seconds=10)
    reader = uploads.VideoReader(mp4)
    reg = TrackRegistry((768, 576), None, [], [])
    stamps, frames_with_ids, seen = [], 0, {}
    while True:
        frame, t = reader.next(1 / 15)
        if frame is None:
            break
        stamps.append(t)
        dets = [d for d in det.detect(frame, t) if d.get("id") is not None]
        reg.update(t, time.time(), dets)
        frames_with_ids += bool(dets)
        for d in dets:
            seen[d["id"]] = seen.get(d["id"], 0) + 1
    reader.close()
    assert 95 <= len(stamps) <= 101 and stamps == sorted(stamps) and 9.5 <= stamps[-1] <= 10.0  # video time, not wall
    assert frames_with_ids >= 80  # people are walking through the whole clip
    assert max(seen.values()) >= 50  # at least one person keeps the same ID for 5+ seconds
    assert 3 <= reg.unique <= 30
    assert det.tracker.next_id > 1
    det.reset()  # Restart: a fresh tracker, IDs count from #1 again, same model (not reloaded)
    assert det.tracker.next_id == 1 and det.tracker.tracks == []
