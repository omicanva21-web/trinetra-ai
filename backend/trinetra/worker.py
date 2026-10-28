"""One thread per camera: read frame -> detect + track -> analyse -> draw -> evidence -> publish.

Uploaded-video cameras (source "upload") run the same per-frame pipeline from `_upload_loop`, which adds
the playback controls (start, pause, resume, restart, stop, remove) and uses the video's own timeline.
"""
from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

from . import config
from .analytics import overlay
from .analytics.pipeline import Analyzer
from .analytics.tracks import TrackRegistry
from .detector import Interrupted, make_detector
from .evidence import Evidence
from .mock_scene import MockScene
from .siteconfig import options_of, resolve
from .sources import MockSource, describe, open_source
from .uploads import SPEEDS, UploadController, VideoReader, mmss

log = logging.getLogger("trinetra.worker")
HUD_TAG = {"simulated": "SIMULATED", "file": "CLIP", "upload": "VIDEO"}


def placeholder(lines: list[str], w: int = 960, h: int = 540) -> bytes:
    img = np.full((h, w, 3), 24, np.uint8)
    for i, text in enumerate(lines):
        scale = 0.9 if i == 0 else 0.6
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2 if i == 0 else 1)
        cv2.putText(img, text, ((w - tw) // 2, h // 2 - 20 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (230, 230, 230) if i == 0 else (160, 170, 180), 2 if i == 0 else 1, cv2.LINE_AA)
    return cv2.imencode(".jpg", img)[1].tobytes()


def banner(frame, text: str, color=(30, 30, 30)) -> bytes:
    """The last picture with a status strip across the bottom (paused, finished, ready, ...)."""
    img = frame.copy()
    h, w = img.shape[:2]
    s = max(0.6, w / 960)
    bar = int(46 * s)
    cv2.rectangle(img, (0, h - bar), (w, h), color, -1)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7 * s, 2)
    cv2.putText(img, text, ((w - tw) // 2, h - (bar - th) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7 * s,
                (240, 240, 240), 2, cv2.LINE_AA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


class CameraWorker(threading.Thread):
    def __init__(self, cam_cfg: dict, get_profile, hub, store):
        super().__init__(daemon=True, name=f"cam-{cam_cfg['id']}")
        self.cfg, self.id = cam_cfg, cam_cfg["id"]
        self.get_profile = get_profile
        self.hub, self.store = hub, store
        self.options = options_of(cam_cfg)
        self.source_kind = describe(cam_cfg["source"])
        self.analyzer: Analyzer | None = None
        self.registry: TrackRegistry | None = None
        self.detector = None
        self.detector_name = ""
        self.evidence = Evidence()
        self.heat = overlay.HeatLayer()
        self.zone_polys: dict = {}
        self.stop_event = threading.Event()
        self.status, self.fps, self.size = "starting", 0.0, None
        self.focus_id: int | None = None
        self.wall_started: dict[str, float] = {}
        self.closed_ids: set[str] = set()
        # uploaded video only
        self.video = UploadController(self.id) if self.source_kind == "upload" else None
        self.last_state: dict | None = None
        self.last_frame = None  # last annotated picture (numpy), for the paused/finished banner
        self.suppressed: set[str] = set()  # incidents already reported by an earlier run of the same video
        self.detect_errors = 0

    # ---- control from the API thread
    def stop(self) -> None:
        self.stop_event.set()

    def set_profile(self, profile: dict) -> None:
        if self.analyzer is not None:
            self.analyzer.set_profile(profile)

    def operator_closed(self, incident_id: str) -> None:
        self.closed_ids.add(incident_id)

    # ---- thread
    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.source_kind == "upload":
                    self._upload_loop()
                else:
                    self._loop()
            except Exception as exc:  # keep the server alive; show the reason on the dashboard
                if f"error: {exc}" != self.status:  # log each new problem once, not every retry
                    log.warning("camera %s: %s (retrying every 3 s)", self.id, exc)
                self.status = f"error: {exc}"
                self.hub.publish({"type": "camera_status", "camera_id": self.id, "status": self.status})
                self.stop_event.wait(3.0)  # then retry (camera re-plugged, file added, ...)

    def _load_detector(self) -> None:
        if self.detector is not None or self.detector_name:
            return
        self.detector, error = make_detector(config.DETECTOR, self.options.get("model", "fast"))
        self.detector_name = self.detector.name if self.detector else f"analytics offline: {error}"

    def _setup(self, frame) -> None:
        """(Re)build everything that depends on the frame size."""
        h, w = frame.shape[:2]
        self.size = (w, h)
        cfg_px = resolve(self.cfg, w, h)
        self.analyzer = Analyzer(cfg_px, self.get_profile())
        self.analyzer.tracker.operator_closed = self.closed_ids
        self.zone_polys = {z.id: z.polygon_px.reshape(-1, 2) for z in self.analyzer.zones}
        crowd = self.options.get("model") == "crowd"
        self.registry = TrackRegistry((w, h), self.analyzer.calib, self.analyzer.zones, cfg_px.get("lines", []),
                                      finalize_s=6.5 if crowd else 2.0, estimate_speed=not crowd)
        self.heat = overlay.HeatLayer()

    def _waiting(self) -> None:
        if self.status != "waiting for browser camera":
            self.status = "waiting for browser camera"
            self.hub.set_frame(self.id, placeholder(["Waiting for the browser camera",
                                                     "Open the Tracking page and press Start camera"]))
            self.hub.publish({"type": "camera_status", "camera_id": self.id, "status": self.status})

    def _detect(self, frame, t: float, source) -> list[dict]:
        if self.source_kind == "simulated":
            return source.dets
        if self.detector is None:
            return []
        if self.source_kind != "upload":
            return self.detector.detect(frame, t)
        try:  # uploaded video: one bad frame must not end the run
            dets = self.detector.detect(frame, t)
            self.detect_errors = 0
            return dets
        except Interrupted:
            raise
        except Exception as exc:
            self.detect_errors += 1
            if self.detect_errors == 1:
                log.warning("camera %s: detection failed on one frame (%s); continuing", self.id, exc)
            if self.detect_errors > 25:
                raise RuntimeError(f"the detector keeps failing ({exc})") from exc
            return []

    def _process(self, frame, t: float, source, tag: str, clock: str | None = None):
        """Detect, track, analyse, draw and store evidence for one frame. Returns (state, annotated frame)."""
        if self.size != (frame.shape[1], frame.shape[0]) or self.analyzer is None:
            self._setup(frame)
        dets = self._detect(frame, t, source)
        offline = self.source_kind != "simulated" and self.detector is None
        self.status = self.detector_name if offline else "running"

        # unconfirmed boxes (no ID yet: one-off or weak detections) are drawn grey but not counted
        counted = [d for d in dets if d.get("id") is not None]
        for d in dets:
            if d.get("demoted") is not None:  # was given an ID, turned out to be a static object
                self.registry.discard(d["demoted"])
        state, events = self.analyzer.analyze(counted, t)
        track_events = self.registry.update(t, time.time(), counted)
        if self.focus_id is not None and self.focus_id not in self.registry.active:
            self.focus_id = None  # the person being followed has left the view
        state["tracking"] = self.registry.snapshot(self.focus_id)
        for d in dets:  # feet for the overlay (the analyzer added them to counted ones)
            d.setdefault("foot", ((d["box"][0] + d["box"][2]) / 2, d["box"][3]))
        annotated = overlay.draw(frame, dets, state, self.heat, self.zone_polys, self.registry,
                                 self.options, self.focus_id, {"tag": tag, "fps": self.fps, "clock": clock})
        self.evidence.push(annotated, now=t if self.source_kind == "upload" else None)
        for e in events:
            self._on_event(e, annotated)
        for te in track_events:
            self._on_track_event(te)
        return state, annotated

    def _loop(self) -> None:
        if self.source_kind == "simulated":
            source = MockSource(resolve(self.cfg, MockScene.W, MockScene.H))
            self.detector_name = "simulated people (no AI)"
        else:
            source = open_source(self.cfg)
            self._load_detector()
        tag = HUD_TAG.get(self.source_kind, "LIVE")
        period = 1.0 / max(1.0, min(float(self.options["max_fps"]), config.ANALYSIS_FPS))
        last_pub = last_raw = 0.0
        try:
            while not self.stop_event.is_set():
                tick = time.monotonic()
                frame, t = source.read(tick)
                if frame is None:  # browser camera: nothing new yet
                    if tick - getattr(source, "last_frame_time", 0.0) > 2.0:
                        self._waiting()
                    continue
                state, annotated = self._process(frame, t, source, tag)

                ok, jpg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
                raw = None
                if tick - last_raw >= 1.0:
                    ok_raw, raw_jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    raw, last_raw = (raw_jpg.tobytes() if ok_raw else None), tick
                if ok:
                    self.hub.set_frame(self.id, jpg.tobytes(), raw, self.size)
                if tick - last_pub >= 0.5:
                    state.update(fps=round(self.fps, 1), status=self.status, detector=self.detector_name,
                                 simulated=self.source_kind == "simulated", source_kind=self.source_kind,
                                 size=list(self.size), ts=time.time())
                    self.hub.publish(state)
                    last_pub = tick
                took = time.monotonic() - tick
                self.fps = 0.85 * self.fps + 0.15 * (1.0 / max(took, period))
                if took < period:
                    self.stop_event.wait(period - took)
        finally:
            source.close()

    # ------------------------------------------------------------------ uploaded video
    def _video_status_text(self) -> str:
        v = self.video
        if v.state == "processing":
            return "running"
        if v.state == "empty":
            return "no video uploaded"
        if v.state == "error":
            return f"video error: {v.message}"
        return f"video {v.state}"

    def _video_frame(self) -> None:
        """Picture shown while not processing: placeholder, first frame (ready) or last frame with a banner."""
        v = self.video
        if v.state == "empty":
            self.hub.set_frame(self.id, placeholder(["Camera 4 - no video uploaded",
                                                     "Press Upload video on this card to choose a recording"]))
            return
        if v.state == "ready" and self.last_frame is None and v.path is not None:
            reader = None
            try:
                reader = VideoReader(v.path, v.meta.get("fps"))
                first = reader.first_frame()
            except Exception:
                first = None
            finally:
                if reader:
                    reader.close()
            if first is None:
                self.hub.set_frame(self.id, placeholder(["The uploaded video could not be read", "Remove it and upload it again"]))
                return
            raw = cv2.imencode(".jpg", first, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
            self.hub.set_frame(self.id, banner(first, "Ready - press Start processing", (90, 60, 20)), raw,
                               (first.shape[1], first.shape[0]))
            return
        if self.last_frame is None:
            return
        pos = f"{mmss(v.position)} / {mmss(v.meta.get('duration_s') if v.meta else None)}"
        text = {"paused": f"Paused at {pos} - press Resume",
                "completed": "Finished - Restart to run it again" if not v.ended_early else f"Video ended early at {mmss(v.position)} (rest unreadable)",
                "stopped": f"Stopped at {pos} - Start processing runs it again from the beginning",
                "error": f"Error: {v.message}"[:90],
                "ready": "Ready - press Start processing"}.get(v.state, v.state)
        color = (20, 20, 160) if v.state == "error" else (90, 60, 20)
        self.hub.set_frame(self.id, banner(self.last_frame, text, color))

    def _reset_analysis(self) -> None:
        """Fresh tracking for a new run: IDs, counts, zones, incident state, evidence buffer."""
        self.analyzer = None  # rebuilt with the next frame (_setup)
        self.registry = None
        self.focus_id = None
        self.last_state = None
        self.heat = overlay.HeatLayer()
        self.evidence.reset()
        if self.detector is not None and hasattr(self.detector, "reset"):
            self.detector.reset()

    def _end_session(self) -> None:
        """The run ended (finished, stopped, restarted, removed): close live incidents and save open visits."""
        t_end = self.video.position
        if self.analyzer is not None:
            for e in self.analyzer.finish(t_end):
                self._on_event(e, None)
        if self.registry is not None:
            for te in self.registry.update(t_end + self.registry.finalize_s + 0.01, time.time(), []):
                self._on_track_event(te)
        self.evidence.reset()

    def _apply(self, action: str, kw: dict, reader):
        """Runs in the worker thread. Returns (result, reader)."""
        v = self.video
        has_video = v.meta is not None

        def fail(msg):
            return {"ok": False, "error": msg}, reader

        if action == "speed":
            sp = kw.get("speed")
            if sp is None or float(sp) not in SPEEDS:
                return fail(f"speed must be one of {', '.join(str(s) for s in SPEEDS)} (0 = as fast as possible)")
            v.speed, v.anchor = float(sp), None
            return {"ok": True}, reader
        if kw.get("speed") is not None and float(kw["speed"]) in SPEEDS:
            v.speed = float(kw["speed"])

        if action == "load":
            if v.state in ("processing", "paused"):
                return fail("Stop processing before uploading another video.")
            if reader:
                reader.close()
            v.meta, v.path = v.store.replace(kw["path"], kw["meta"])
            self.suppressed.clear()
            self._reset_analysis()
            self.last_frame = None
            v.state, v.message, v.position, v.session, v.timeline = "ready", "", 0.0, None, []
            v.frames_analysed = 0
            log.info("camera %s: video uploaded (%.1f MB, %s)", self.id, (v.meta.get("size_bytes") or 0) / 1e6,
                     mmss(v.meta.get("duration_s")))
            return {"ok": True}, None

        if action == "remove":
            if reader:
                self._end_session()
                reader.close()
            try:
                v.store.remove()
            except OSError as exc:
                return {"ok": False, "error": f"could not delete the video file ({exc})"}, None
            v.meta = v.path = None
            self._reset_analysis()
            self.last_frame = None
            v.state, v.message, v.position, v.session, v.timeline = "empty", "", 0.0, None, []
            v.frames_analysed = 0
            return {"ok": True}, None

        if not has_video:
            return fail("No video uploaded yet. Press Upload video first.")

        if action in ("start", "restart") and not (action == "start" and v.state == "paused"):
            if action == "start" and v.state == "processing":
                return {"ok": True, "note": "already processing"}, reader  # never a second loop
            if reader:
                self._end_session()
                reader.close()
                reader = None
            try:
                reader = VideoReader(v.path, v.meta.get("fps"))
            except Exception as exc:
                v.state, v.message = "error", str(exc)
                return fail(str(exc))
            self._reset_analysis()
            v.new_session()
            v.state, v.message = "processing", ""
            return {"ok": True}, reader
        if action in ("resume", "start"):  # start while paused = resume
            if v.state != "paused":
                return fail("Nothing is paused.")
            v.state, v.anchor = "processing", None
            v.recent.clear()  # the pause is not processing time
            return {"ok": True}, reader
        if action == "pause":
            if v.state != "processing":
                return fail("Nothing is processing.")
            v.state = "paused"
            return {"ok": True}, reader
        if action == "stop":
            if v.state not in ("processing", "paused"):
                return fail("Nothing is processing.")
            self._end_session()
            if reader:
                reader.close()
            v.state = "stopped"
            return {"ok": True}, None
        return fail(f"unknown action {action!r}")

    def _video_state(self) -> dict:
        """State message for the dashboard while the video is not being processed (or between frames)."""
        v = self.video
        base = self.last_state or {"type": "state", "camera_id": self.id, "camera_name": self.cfg.get("name", self.id),
                                   "t": 0, "people": 0, "vehicles": 0, "score": 0, "level": "LOW", "zones": []}
        st = dict(base)
        if v.state != "paused" or self.last_state is None:  # nothing is on screen "now" any more
            st.update(people=0, vehicles=0, score=0, level="LOW",
                      zones=[{**z, "count": 0, "score": 0, "level": "LOW", "reasons": [], "density": None,
                              "eta_s": None, "trend": "unknown", "max_dwell_s": 0, "ids": []} for z in base["zones"]])
        st["tracking"] = self.registry.snapshot(None) if self.registry is not None else None
        if st["tracking"] is not None and v.state != "paused":
            st["tracking"]["active"], st["tracking"]["active_count"], st["tracking"]["people_tracked"] = [], 0, 0
        return st

    def _publish_video(self, state: dict) -> None:
        v = self.video
        self.status = self._video_status_text()
        fps, _ = v.rates()
        state.update(fps=round(fps, 1), status=self.status, detector=self.detector_name, simulated=False,
                     source_kind="upload", size=list(self.size) if self.size else None, ts=time.time(), video=v.info())
        self.hub.publish(state)

    def _upload_loop(self) -> None:
        v = self.video
        # the model (up to 101 MB for Dense crowd) loads in the background, so the card and its buttons
        # answer at once; processing starts as soon as it is ready
        loader = threading.Thread(target=self._load_detector, daemon=True, name=f"model-{self.id}")
        v.model_loading = True
        loader.start()
        period = 1.0 / max(1.0, min(float(self.options["max_fps"]), config.ANALYSIS_FPS))
        reader = None
        last_pub = 0.0
        shown = None
        try:
            while not self.stop_event.is_set():
                # 1. controls from the dashboard (blocks briefly when idle, so an idle camera costs nothing)
                for action, kw, done, box in v.take(0.0 if v.state == "processing" else 0.25):
                    try:
                        box["result"], reader = self._apply(action, kw, reader)
                    except Exception as exc:  # a failed command must not kill the worker
                        log.exception("camera %s: video %s failed", self.id, action)
                        box["result"] = {"ok": False, "error": str(exc)}
                    shown = None
                    if v.state != "processing":  # the new picture is up before the dashboard gets the answer
                        self._video_frame()
                        shown = v.state
                    box["result"]["video"] = v.info()
                    done.set()
                    last_pub = 0.0

                tick = time.monotonic()
                if v.model_loading and not loader.is_alive():
                    v.model_loading = False
                    last_pub = 0.0
                    if self.detector is not None and hasattr(self.detector, "should_stop"):
                        self.detector.should_stop = lambda: not v.commands.empty() or self.stop_event.is_set()
                # 2. one frame
                if v.state == "processing" and reader is not None and v.model_loading:
                    if tick - last_pub >= 0.5:
                        self._publish_video(self._video_state())
                        last_pub = tick
                    self.stop_event.wait(0.1)
                    continue
                if v.state == "processing" and reader is not None:
                    try:
                        frame, t = reader.next(period)
                    except Exception as exc:
                        v.state, v.message = "error", f"decoding stopped: {exc}"
                        self._end_session()
                        reader.close()
                        reader = None
                        continue
                    if frame is None:  # end of the video
                        dur = v.meta.get("duration_s")
                        v.ended_early = bool(dur and v.position < dur - max(2.0, 0.05 * dur))
                        self._end_session()
                        reader.close()
                        reader = None
                        v.state = "completed"
                        log.info("camera %s: video finished (%d frames analysed)", self.id, v.frames_analysed)
                        continue
                    dur = v.meta.get("duration_s")
                    try:
                        state, annotated = self._process(frame, t, None, "VIDEO", f"{mmss(t)} / {mmss(dur)}")
                    except Interrupted:
                        continue  # a button was pressed mid-frame: answer it now (this one frame is skipped)
                    except Exception as exc:
                        v.state, v.message = "error", str(exc)
                        self._end_session()
                        reader.close()
                        reader = None
                        continue
                    self.last_state, self.last_frame = state, annotated
                    v.analysed(time.monotonic(), t)
                    tr = state["tracking"]
                    v.add_sample({"vt": round(t, 2), "people": state["people"], "tracked": tr["active_count"],
                                  "unique": tr["unique"], "in": sum(ln["in"] for ln in tr["lines"]),
                                  "out": sum(ln["out"] for ln in tr["lines"]), "fps": round(v.rates()[0], 1),
                                  "zones": {z["id"]: {"count": z["count"], "density": z["density"], "score": z["score"]}
                                            for z in state["zones"]}})
                    ok, jpg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    raw = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes() \
                        if v.frames_analysed % 15 == 1 else None
                    if ok:
                        self.hub.set_frame(self.id, jpg.tobytes(), raw, self.size)
                    if tick - last_pub >= 0.5:
                        st = dict(state)
                        self._publish_video(st)
                        last_pub = tick
                    # pace: never faster than the chosen speed; if the laptop is slower, the video just plays slower
                    if v.speed > 0:
                        now = time.monotonic()
                        if v.anchor is None:
                            v.anchor = (now, t)
                        due = v.anchor[0] + (t - v.anchor[1]) / v.speed
                        if due > now:  # wait, but answer Pause/Stop/... at once
                            end = min(due, now + 1.0)
                            while time.monotonic() < end and v.commands.empty() and not self.stop_event.is_set():
                                self.stop_event.wait(0.02)
                        elif now - due > 0.5:
                            v.anchor = (now, t)  # behind: carry on from here instead of sprinting to catch up
                    took = time.monotonic() - tick
                    self.fps = 0.85 * self.fps + 0.15 * (1.0 / max(took, 1e-3))
                    continue

                # 3. idle (no video, ready, paused, finished, stopped, error)
                if shown != v.state:
                    self._video_frame()
                    shown = v.state
                if tick - last_pub >= 0.5:
                    self._publish_video(self._video_state())
                    last_pub = tick
        finally:
            if reader:
                reader.close()

    # ------------------------------------------------------------------ events
    def _video_extra(self) -> dict:
        v = self.video
        return {"source_kind": "upload", "video_id": v.video_key() or None,
                "video_name": v.meta.get("name") if v.meta else None}

    def _on_event(self, event: dict, frame) -> None:
        inc_id, action = event["incident"]["id"], event["action"]
        extra = None
        if self.video is not None:
            inc = event["incident"]
            if inc_id in self.suppressed:
                return
            extra = {**self._video_extra(), "video_ts": round(float(inc.get("started_at", 0.0)), 2),
                     "video_end": round(float(inc.get("updated_at", inc.get("started_at", 0.0))), 2)}
            if action == "opened" and extra["video_id"]:
                try:
                    dup = self.store.find_video_incident(self.id, extra["video_id"], inc["zone_id"], extra["video_ts"])
                except Exception:
                    dup = None
                if dup:  # the same moment of the same video was already reported by an earlier run
                    self.suppressed.add(inc_id)
                    return
        self.wall_started.setdefault(inc_id, time.time())
        try:
            row = self.store.upsert_from_event(event, self.wall_started[inc_id], extra)
            if action in ("opened", "reopened", "escalated") and frame is not None:
                snap = self.evidence.snapshot(inc_id, frame)  # newest snapshot shows the worst moment so far
                row = self.store.set_evidence(inc_id, snapshot=snap) or row
                if action == "opened":
                    self.evidence.start_clip(inc_id, self._clip_done)
        except Exception:  # storage failed: keep analysing and still alert the operator live
            log.exception("could not store incident %s", inc_id)
            inc = event["incident"]
            row = {**inc, **(extra or {}), "status": "open", "started_at": self.wall_started[inc_id],
                   "updated_at": time.time(), "has_snapshot": False, "has_clip": False, "unsaved": True}
        self.hub.publish({"type": "incident", "action": action, "incident": row})

    def _on_track_event(self, ev: dict) -> None:
        session = self.video.session if self.video is not None else None
        try:
            if ev["type"] == "crossing":
                self.store.save_crossing(self.id, ev, session)
            elif ev["type"] == "track_done":
                self.store.save_track(self.id, ev, session)
        except Exception:
            log.exception("could not store a tracking event")
        brief = {k: v for k, v in ev.items() if k not in ("path", "type", "t", "started_t", "ended_t")}
        if session:  # uploaded video: when it happened in the recording
            brief["video_ts"] = ev.get("t", ev.get("ended_t"))
            brief["session"] = session
        self.hub.publish({"type": "track_event", "event": ev["type"], "camera_id": self.id, **brief})

    def _clip_done(self, inc_id: str, path: str) -> None:
        try:
            row = self.store.set_evidence(inc_id, clip=path)
        except Exception:
            log.exception("could not store clip for %s", inc_id)
            return
        if row:
            self.hub.publish({"type": "incident", "action": "evidence", "incident": row})
