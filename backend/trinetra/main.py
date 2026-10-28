"""FastAPI app: REST, WebSockets, MJPEG streams, camera/zone setup, tracking, analytics, and the React app."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from . import config, siteconfig, uploads
from .db import Store
from .hub import Hub
from .siteconfig import CameraIn, ProfileIn
from .sources import BROWSER, describe
from .worker import CameraWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
hub = Hub()
store = Store()
workers: dict[str, CameraWorker] = {}
runtime = {"profile": "station", "profiles": {}, "site": {}}
_cam_lock = threading.Lock()


def current_profile() -> dict:
    return runtime["profiles"][runtime["profile"]]


def start_worker(cam: dict) -> None:
    if not cam.get("enabled", True):
        return
    w = CameraWorker(cam, current_profile, hub, store)
    workers[cam["id"]] = w
    w.start()


def stop_worker(cam_id: str) -> None:
    w = workers.pop(cam_id, None)
    if w:
        w.stop()
        w.join(timeout=5)
    hub.forget(cam_id)


def find_camera(camera_id: str) -> dict | None:
    return next((c for c in runtime["site"]["cameras"] if c["id"] == camera_id), None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    runtime["site"] = siteconfig.load_site()
    if siteconfig.ensure_upload_camera(runtime["site"]):  # older configs get Camera 4 (uploaded video) once
        siteconfig.save_site(runtime["site"])
    uploads.clean_incoming()
    runtime["profiles"] = siteconfig.load_profiles()
    runtime["profile"] = runtime["site"].get("profile", "station")
    if runtime["profile"] not in runtime["profiles"]:
        runtime["profile"] = next(iter(runtime["profiles"]))
    for cam in runtime["site"]["cameras"]:
        start_worker(cam)
    yield
    for cid in list(workers):
        workers[cid].stop()


app = FastAPI(title="Trinetra AI", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[config.FRONTEND_ORIGIN], allow_methods=["*"], allow_headers=["*"])


def require_token(x_operator_token: str | None = Header(default=None), token: str | None = Query(default=None)):
    if config.OPERATOR_TOKEN and (x_operator_token or token) != config.OPERATOR_TOKEN:
        raise HTTPException(status_code=401, detail="operator token required")


class ActionIn(BaseModel):
    action: Literal["acknowledge", "dispatch", "false_alarm", "resolve"]
    note: str = Field(default="", max_length=500)


class ProfileSwitch(BaseModel):
    name: str


class FocusIn(BaseModel):
    track_id: int | None = None


def camera_view(cam: dict) -> dict:
    w = workers.get(cam["id"])
    size = hub.sizes.get(cam["id"]) or (w.size if w else None)
    view = siteconfig.normalised_view(cam, *(size or (None, None)))
    state = hub.states.get(cam["id"], {})
    view.update(enabled=cam.get("enabled", True), source_kind=describe(cam["source"]),
                simulated=str(cam["source"]) == "mock", size=list(size) if size else None,
                status=(w.status if w else "disabled"), fps=round(w.fps, 1) if w else 0,
                detector=(w.detector_name if w else ""), people=state.get("people"), level=state.get("level"),
                browser_connected=BROWSER.senders.get(cam["id"], 0) > 0,
                video=(w.video.info() if w and w.video else None))
    return view


# ------------------------------------------------------------------ status and configuration
@app.get("/api/health")
def health():
    return {"ok": True, "profile": runtime["profile"], "detector_mode": config.DETECTOR,
            "cameras": [{"id": k, "status": w.status, "fps": round(w.fps, 1), "detector": w.detector_name}
                        for k, w in workers.items()]}


@app.get("/api/config")
def get_config():
    return {"site": runtime["site"].get("site", ""), "profile": runtime["profile"],
            "profiles": {k: v.get("label", k) for k, v in runtime["profiles"].items()},
            "thresholds": current_profile(), "auth_required": bool(config.OPERATOR_TOKEN),
            "cameras": [camera_view(c) for c in runtime["site"]["cameras"]]}


@app.get("/api/cameras")
def list_cameras():
    return [camera_view(c) for c in runtime["site"]["cameras"]]


@app.get("/api/cameras/{camera_id}/frame.jpg", dependencies=[Depends(require_token)])
def camera_frame(camera_id: str):
    jpg = hub.get_frame(camera_id, raw=True)
    if not jpg:
        raise HTTPException(404, "no frame yet: is the camera enabled and running?")
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def _save_and_publish() -> None:
    siteconfig.save_site(runtime["site"])
    hub.publish({"type": "config_changed"})


@app.post("/api/cameras", dependencies=[Depends(require_token)])
def add_camera(body: CameraIn):
    with _cam_lock:
        cam_id = siteconfig.new_camera_id(runtime["site"])
        cam = siteconfig.camera_to_store(cam_id, body)
        runtime["site"]["cameras"].append(cam)
        _save_and_publish()
        start_worker(cam)
    return camera_view(cam)


@app.put("/api/cameras/{camera_id}", dependencies=[Depends(require_token)])
def update_camera(camera_id: str, body: CameraIn):
    with _cam_lock:
        cams = runtime["site"]["cameras"]
        idx = next((i for i, c in enumerate(cams) if c["id"] == camera_id), None)
        if idx is None:
            raise HTTPException(404, "unknown camera")
        old = cams[idx]
        cam = siteconfig.camera_to_store(camera_id, body)
        if str(old["source"]) == "mock" and cam["source"] == "mock" and "calibration" not in cam and old.get("calibration"):
            cam["calibration"] = old["calibration"]  # the simulated floor keeps its calibration
        cams[idx] = cam
        _save_and_publish()
        stop_worker(camera_id)
        start_worker(cam)
    if describe(cam["source"]) == "upload" and cam.get("enabled", True):
        for _ in range(30):  # its picture is up within a moment: answer once it is, so the page never asks too early
            if hub.get_frame(camera_id, raw=True) or hub.get_frame(camera_id):
                break
            threading.Event().wait(0.05)
    return camera_view(cam)


@app.delete("/api/cameras/{camera_id}", dependencies=[Depends(require_token)])
def delete_camera(camera_id: str):
    with _cam_lock:
        cams = runtime["site"]["cameras"]
        if not any(c["id"] == camera_id for c in cams):
            raise HTTPException(404, "unknown camera")
        removed = next(c for c in cams if c["id"] == camera_id)
        runtime["site"]["cameras"] = [c for c in cams if c["id"] != camera_id]
        _save_and_publish()
        stop_worker(camera_id)
        if describe(removed["source"]) == "upload":  # its uploaded video goes too
            try:
                uploads.VideoStore(camera_id).remove()
            except (OSError, ValueError):
                logging.getLogger("trinetra").warning("could not delete the uploaded video of %s", camera_id)
    return {"deleted": camera_id}


@app.get("/api/profiles")
def get_profiles():
    return {"current": runtime["profile"], "profiles": runtime["profiles"]}


@app.put("/api/profiles/{name}", dependencies=[Depends(require_token)])
def update_profile(name: str, body: ProfileIn):
    if not siteconfig.SAFE_ID.match(name):
        raise HTTPException(422, "profile names use letters, digits, - and _")
    runtime["profiles"][name] = body.model_dump()
    siteconfig.save_profiles(runtime["profiles"])
    if name == runtime["profile"]:
        for w in workers.values():
            w.set_profile(current_profile())
    hub.publish({"type": "profile", "profile": runtime["profile"], "thresholds": current_profile()})
    return runtime["profiles"][name]


@app.post("/api/profile", dependencies=[Depends(require_token)])
def set_profile(body: ProfileSwitch):
    if body.name not in runtime["profiles"]:
        raise HTTPException(404, "unknown profile")
    runtime["profile"] = body.name
    runtime["site"]["profile"] = body.name
    siteconfig.save_site(runtime["site"])
    for w in workers.values():
        w.set_profile(current_profile())
    hub.publish({"type": "profile", "profile": body.name, "thresholds": current_profile()})
    return {"profile": body.name}


# ------------------------------------------------------------------ tracking
@app.get("/api/cameras/{camera_id}/tracks")
def camera_tracks(camera_id: str, recent: int = Query(default=40, ge=0, le=200)):
    if find_camera(camera_id) is None:
        raise HTTPException(404, "unknown camera")
    w = workers.get(camera_id)
    live = w.registry.paths(recent) if w and w.registry else {"active": [], "finished": []}
    try:
        if w and w.video:  # uploaded video: only the current run of the current video
            finished = store.recent_tracks(camera_id, recent, w.video.session) if w.video.session else []
        else:
            finished = store.recent_tracks(camera_id, recent)
    except Exception:  # database trouble: fall back to what this session remembers
        finished = live["finished"]
    snap = w.registry.snapshot(w.focus_id) if w and w.registry else None
    return {"active": live["active"], "finished": finished, "summary": snap}


@app.post("/api/cameras/{camera_id}/focus")
def camera_focus(camera_id: str, body: FocusIn):
    w = workers.get(camera_id)
    if w is None:
        raise HTTPException(404, "camera not running")
    w.focus_id = body.track_id
    return {"focus": w.focus_id}


@app.get("/api/tracking/stats")
def tracking_stats(camera_id: str | None = None, window_min: int = Query(default=30, ge=1, le=1440)):
    bucket = 1 if window_min <= 60 else max(1, window_min // 60)
    w = workers.get(camera_id) if camera_id else None
    if w and w.video:  # uploaded video: the current run, on the video's own timeline
        session = w.video.session or "none"
        return store.tracking_stats(camera_id, window_min, bucket, session=session, until_s=w.video.position)
    return store.tracking_stats(camera_id, window_min, bucket)


# ------------------------------------------------------------------ incidents
@app.get("/api/incidents")
def list_incidents(status: str | None = None, level: str | None = None, camera_id: str | None = None,
                   limit: int = Query(default=100, ge=1, le=1000)):
    return store.list(status, limit, level, camera_id)


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    row = store.get(incident_id)
    if row is None:
        raise HTTPException(404, "incident not found")
    return {**row.public(), "actions": store.actions(incident_id)}


@app.post("/api/incidents/{incident_id}/action", dependencies=[Depends(require_token)])
def act(incident_id: str, body: ActionIn):
    row = store.act(incident_id, body.action, body.note)
    if row is None:
        raise HTTPException(404, "incident not found")
    if body.action in ("resolve", "false_alarm") and row["camera_id"] in workers:
        workers[row["camera_id"]].operator_closed(incident_id)
    hub.publish({"type": "incident", "action": body.action, "incident": row})
    return row


def _evidence_file(incident_id: str, attr: str) -> Path:
    row = store.get(incident_id)  # look up by ID: never trust a path from the client
    path = getattr(row, attr, None) if row else None
    if not path or not Path(path).exists():
        raise HTTPException(404, "evidence not found")
    return Path(path)


@app.get("/api/incidents/{incident_id}/snapshot", dependencies=[Depends(require_token)])
def snapshot(incident_id: str):
    return FileResponse(_evidence_file(incident_id, "snapshot_path"), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/incidents/{incident_id}/clip", dependencies=[Depends(require_token)])
def clip(incident_id: str):
    return FileResponse(_evidence_file(incident_id, "clip_path"), media_type="video/mp4")


# ------------------------------------------------------------------ analytics
@app.get("/api/metrics")
def metrics(minutes: float = Query(default=10, gt=0, le=30)):
    return hub.get_history(minutes)


@app.get("/api/stats")
def stats(window_min: int = Query(default=60, ge=10, le=1440), scope: Literal["all", "live", "video"] = "all",
          camera_id: str | None = None, video_id: str | None = None):
    """scope=live leaves out uploaded-video incidents; scope=video with camera_id (and video_id) shows only those."""
    s = store.stats(window_min=window_min, bucket_min=max(1, window_min // 12), scope=scope,
                    camera_id=camera_id if scope == "video" else None, video_id=video_id if scope == "video" else None)
    # "now" numbers come from live and simulated cameras only: a recording is not happening now
    live = [x for x in hub.states.values() if x.get("source_kind") != "upload"]
    kinds = [describe(c["source"]) for c in runtime["site"]["cameras"] if c.get("enabled", True)]
    s["live"] = {"people": sum(x.get("people", 0) for x in live),
                 "vehicles": sum(x.get("vehicles", 0) for x in live),
                 "cameras_running": sum(1 for w in workers.values() if w.status == "running"),
                 "cameras_total": len(runtime["site"]["cameras"]),
                 "uploaded_videos": kinds.count("upload"),
                 "high_zones": sum(1 for x in live for z in x.get("zones", []) if z["level"] == "HIGH")}
    return s


# ------------------------------------------------------------------ uploaded video (Camera 4)
class VideoControl(BaseModel):
    action: Literal["start", "pause", "resume", "restart", "stop", "speed"]
    speed: float | None = Field(default=None, ge=0, le=8)  # 0 = as fast as possible


def _upload_worker(camera_id: str) -> CameraWorker:
    cam = find_camera(camera_id)
    if cam is None:
        raise HTTPException(404, "unknown camera")
    if describe(cam["source"]) != "upload":
        raise HTTPException(400, "this camera does not take uploaded videos")
    w = workers.get(camera_id)
    if w is None or w.video is None:
        if cam.get("enabled", True):
            raise HTTPException(409, "this camera is restarting (settings were just saved); try again in a moment")
        raise HTTPException(409, "this camera is disabled: enable it on the Setup page first")
    return w


def _video_result(result: dict) -> dict:
    if not result.get("ok"):
        raise HTTPException(409, result.get("error") or "the video could not do that now")
    return result


@app.get("/api/cameras/{camera_id}/video")
def video_status(camera_id: str):
    return _upload_worker(camera_id).video.info()


@app.get("/api/cameras/{camera_id}/video/timeline")
def video_timeline(camera_id: str):
    v = _upload_worker(camera_id).video
    return {"session": v.session, "duration_s": (v.meta or {}).get("duration_s"), "samples": list(v.timeline)}


@app.post("/api/cameras/{camera_id}/video", dependencies=[Depends(require_token)])
async def upload_video(camera_id: str, request: Request, x_filename: str | None = Header(default=None)):
    """Raw file body (no multipart): streamed to disk in chunks, checked, then handed to the camera worker."""
    w = _upload_worker(camera_id)
    v = w.video
    if v.state in ("processing", "paused"):
        raise HTTPException(409, "Stop processing before uploading another video.")
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"This video is {int(declared) / 1048576:.0f} MB; the limit is {config.MAX_UPLOAD_MB} MB "
                                 "(TRINETRA_MAX_UPLOAD_MB in .env).")
    if not v.upload_lock.acquire(blocking=False):
        raise HTTPException(409, "Another upload to this camera is still running.")
    tmp = None
    handed_over = False
    try:
        uploads.check_disk(int(declared) if declared and declared.isdigit() else 0)
        tmp = uploads.incoming_path()
        size, head = 0, b""
        digest = hashlib.sha256()  # the same file uploaded again is recognised (no duplicate incidents)
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                digest.update(chunk)
                if size > limit:
                    raise uploads.UploadError(413, f"This video is larger than the {config.MAX_UPLOAD_MB} MB limit "
                                                   "(TRINETRA_MAX_UPLOAD_MB in .env).")
                if len(head) < 4096:
                    head += chunk[: 4096 - len(head)]
                f.write(chunk)
        if size == 0:
            raise uploads.UploadError(400, "The file is empty.")
        container = uploads.sniff_container(head)
        if container is None:
            raise uploads.UploadError(415, f"This file is not a video Trinetra can read. Accepted formats: {uploads.ACCEPTED}.")
        meta = await run_in_threadpool(uploads.probe, tmp)
        meta.update(id=uuid.uuid4().hex, video_id=digest.hexdigest()[:32],
                    name=uploads.clean_display_name(unquote(x_filename or "")),
                    container=container, size_bytes=size, uploaded_at=time.time())
        handed_over = True  # from here the worker owns the file (it moves it into place)
        result = await run_in_threadpool(v.command, "load", path=tmp, meta=meta)
        if not result.get("ok"):
            handed_over = False
        return _video_result(result)["video"]
    except uploads.UploadError as exc:
        raise HTTPException(exc.status, exc.message) from None
    except ClientDisconnect:
        raise HTTPException(400, "The upload was interrupted.") from None
    finally:
        v.upload_lock.release()
        if tmp is not None and not handed_over:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


@app.post("/api/cameras/{camera_id}/video/control", dependencies=[Depends(require_token)])
async def video_control(camera_id: str, body: VideoControl):
    w = _upload_worker(camera_id)
    result = await run_in_threadpool(w.video.command, body.action, speed=body.speed)
    return _video_result(result)["video"]


@app.delete("/api/cameras/{camera_id}/video", dependencies=[Depends(require_token)])
async def remove_video(camera_id: str):
    w = _upload_worker(camera_id)
    if w.video.upload_lock.locked():
        raise HTTPException(409, "An upload is still running.")
    result = await run_in_threadpool(w.video.command, "remove")
    return _video_result(result)["video"]


# ------------------------------------------------------------------ live video and push
@app.get("/stream/{camera_id}.mjpg", dependencies=[Depends(require_token)])
async def stream(camera_id: str):
    if find_camera(camera_id) is None:
        raise HTTPException(404, "unknown camera")

    async def frames():
        # The boundary goes right after each picture: browsers only show a part once the next boundary
        # arrives, so a camera that is idle (uploaded video ready, paused or finished) would stay blank.
        # An unchanged picture is re-sent every 2 s for the same reason.
        yield b"--frame\r\n"
        last, sent_at = None, 0.0
        while True:
            jpg = hub.get_frame(camera_id)
            now = time.monotonic()
            if jpg and (jpg is not last or now - sent_at >= 2.0):
                last, sent_at = jpg, now
                yield (b"Content-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
                       + jpg + b"\r\n--frame\r\n")
            await asyncio.sleep(0.03)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@app.websocket("/ws/camera/{camera_id}")
async def camera_ingest(websocket: WebSocket, camera_id: str, token: str | None = None):
    """The dashboard sends webcam frames (JPEG, binary messages) for cameras whose source is "browser"."""
    cam = find_camera(camera_id)
    if config.OPERATOR_TOKEN and token != config.OPERATOR_TOKEN:
        await websocket.close(code=1008)
        return
    if cam is None or str(cam["source"]) != "browser":
        await websocket.close(code=1008)
        return
    await websocket.accept()
    BROWSER.connected(camera_id, +1)
    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data and len(data) < 4_000_000:
                BROWSER.put(camera_id, data)
    except WebSocketDisconnect:
        pass
    finally:
        BROWSER.connected(camera_id, -1)


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    hub.clients.add(websocket)
    try:
        await websocket.send_json({"type": "hello", "profile": runtime["profile"], "thresholds": current_profile(),
                                   "states": list(hub.states.values()), "incidents": store.list("open", 50)})
        while True:
            await websocket.receive_text()  # we only push; reading keeps the connection alive
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(websocket)


DIST = config.ROOT / "frontend" / "dist"
if DIST.exists():  # one process serves the dashboard too
    app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
