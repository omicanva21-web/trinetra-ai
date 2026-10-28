"""Uploaded videos (Camera 4): format checks, safe storage, frame reading and the playback controls.

Safety rules
- The browser's file name is only shown on screen. On disk every video gets a server-made name
  (random hex + the extension of the container that was actually detected).
- The type is decided from the file's first bytes and by decoding real frames with OpenCV, not from
  the file name. Uploads that cannot be decoded are deleted at once.
- Uploaded files are never served back over HTTP and never executed: only the camera worker reads them.

Timing
- The analysis clock is the video's own timeline (decoder timestamps, or frame number / FPS), so speeds,
  dwell times and incident times are "time in the video", whatever speed the laptop processes at.
- Processing time (wall clock) is kept separately for the incident log.
"""
from __future__ import annotations

import json
import logging
import math
import queue
import re
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import cv2

from . import config

log = logging.getLogger("trinetra.uploads")

ACCEPTED = "MP4, MOV, AVI, MKV or WEBM"
ACCEPT_EXT = (".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm")
EXT = {"mp4": ".mp4", "mov": ".mov", "avi": ".avi", "mkv": ".mkv", "webm": ".webm"}
_SAFE_CAM = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
_SAFE_FILE = re.compile(r"^[0-9a-f]{32}\.(mp4|mov|avi|mkv|webm)$")
STATES = ("empty", "ready", "processing", "paused", "completed", "stopped", "error")
SPEEDS = (0, 0.25, 0.5, 1, 2, 4, 8)  # 0 = as fast as the computer can


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def mmss(s: float | None) -> str:
    if s is None or not math.isfinite(s):
        return "--:--"
    s = max(0, int(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


# ------------------------------------------------------------------ format checks
def sniff_container(head: bytes) -> str | None:
    """Container from the first bytes of the file (not from its name)."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mov" if head[8:12] == b"qt  " else "mp4"  # ISO media: mp4, m4v, 3gp, mov
    if len(head) >= 8 and head[4:8] in (b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"):
        return "mov"  # older QuickTime files start with another atom
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML: Matroska or WebM
        return "webm" if b"webm" in head[:96] else "mkv"
    return None


def clean_display_name(name: str) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()[:120]
    return name or "video"


def _ffmpeg_header(path: Path) -> dict:
    """Duration and FPS from the container header via the bundled ffmpeg (no full decode)."""
    try:
        import imageio_ffmpeg

        gen = imageio_ffmpeg.read_frames(str(path))
        meta = next(gen)
        gen.close()
        return meta
    except Exception:
        return {}


def probe(path: Path) -> dict:
    """Open the video with OpenCV and decode its first frames; raises UploadError if that fails."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise UploadError(415, f"This file could not be opened as a video. Accepted formats: {ACCEPTED}. "
                                   "If it plays on your computer, export it again as MP4 (H.264).")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise UploadError(415, "The video's format was recognised, but its picture could not be decoded on this "
                                   "computer (unsupported codec or a damaged file). Export it again as MP4 (H.264) "
                                   f"and upload that. Accepted formats: {ACCEPTED}.")
        h, w = frame.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
        decoded = 1
        for _ in range(4):  # a few more frames: catches files with a valid header and broken data
            ok, _f = cap.read()
            decoded += int(bool(ok))
    finally:
        cap.release()
    fps = fps if fps and 1.0 <= fps <= 240.0 else None
    frames = frames if frames > 0 else None
    duration = frames / fps if frames and fps else None
    if duration is None or duration <= 0 or fps is None:
        meta = _ffmpeg_header(path)
        duration = duration or (meta.get("duration") if (meta.get("duration") or 0) > 0 else None)
        fps = fps or (meta.get("fps") if 1.0 <= (meta.get("fps") or 0) <= 240.0 else None)
    codec = "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)).strip() if fourcc > 0 else ""
    if decoded < 2 and (frames or 0) > 1:
        raise UploadError(415, "Only the first frame of this video could be decoded; the file looks damaged. "
                               "Export it again as MP4 (H.264).")
    return {"width": w, "height": h, "fps": round(fps, 3) if fps else None, "frames": frames,
            "duration_s": round(duration, 2) if duration else None,
            "codec": "".join(c for c in codec if c.isprintable())}


def check_disk(needed_bytes: int) -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(config.UPLOAD_DIR).free
    if free < needed_bytes + 200 * 1024 * 1024:
        raise UploadError(507, f"Not enough free disk space for this video ({free // 1048576} MB free).")


def incoming_path() -> Path:
    folder = config.UPLOAD_DIR / "incoming"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{uuid.uuid4().hex}.part"


def clean_incoming() -> None:
    """Remove half-finished uploads left by a crash or a closed window."""
    folder = config.UPLOAD_DIR / "incoming"
    if folder.exists():
        for p in folder.glob("*.part"):
            try:
                p.unlink()
            except OSError:
                pass


class VideoStore:
    """The one current video of one camera: uploads/<camera_id>/<hex>.<ext> plus meta.json."""

    def __init__(self, camera_id: str):
        if not _SAFE_CAM.match(camera_id):
            raise ValueError("unsafe camera id")
        self.dir = config.UPLOAD_DIR / camera_id

    def current(self) -> tuple[dict, Path] | None:
        try:
            meta = json.loads(config.read_text(self.dir / "meta.json"))
        except (OSError, ValueError):
            return None
        name = str(meta.get("file", ""))
        path = self.dir / name
        if not _SAFE_FILE.match(name) or not path.is_file():
            return None
        return meta, path

    def replace(self, tmp: Path, meta: dict) -> tuple[dict, Path]:
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"{meta['id']}{EXT[meta['container']]}"
        dest = self.dir / name
        tmp.replace(dest)  # first: if this fails, the previous video is still there
        for p in self.dir.iterdir():  # then the previous video goes (one video per camera)
            if p.is_file() and p.name not in (name, "meta.json"):
                p.unlink()
        meta = {**meta, "file": name}
        tmp_meta = self.dir / "meta.tmp"
        tmp_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_meta.replace(self.dir / "meta.json")
        return meta, dest

    def remove(self, keep_dir: bool = False) -> None:
        if not self.dir.exists():
            return
        for p in self.dir.iterdir():
            if p.is_file():
                p.unlink()  # raises on Windows if something still has the file open
        if not keep_dir:
            try:
                self.dir.rmdir()
            except OSError:
                pass


class VideoReader:
    """Reads frames in order, at most one per `min_step` seconds of video (skipped frames are only grabbed)."""

    def __init__(self, path: Path, fps_hint: float | None = None):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise RuntimeError("the uploaded video could not be opened (file missing or unreadable)")
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if fps and 1.0 <= fps <= 240.0 else (fps_hint or 25.0)
        self.idx = -1
        self.ts: float | None = None
        self.last_grab_ts = -1.0
        self.bad = 0

    def _stamp(self) -> float:
        ms = self.cap.get(cv2.CAP_PROP_POS_MSEC)
        t = ms / 1000.0 if ms and ms > 0 and math.isfinite(ms) else self.idx / self.fps
        if t <= self.last_grab_ts:  # some files repeat or lack timestamps: never let the clock go back
            t = self.last_grab_ts + 1.0 / self.fps
        self.last_grab_ts = t
        return t

    def first_frame(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def next(self, min_step: float):
        """(frame, video seconds), or (None, None) at the end of the video."""
        while True:
            if not self.cap.grab():
                return None, None
            self.idx += 1
            t = self._stamp()
            if self.ts is not None and t < self.ts + min_step - 0.5 / self.fps:
                continue
            ok, frame = self.cap.retrieve()
            if not ok or frame is None:
                self.bad += 1
                if self.bad > 50:
                    raise RuntimeError(f"too many frames could not be decoded (around {mmss(t)})")
                continue
            self.bad = 0
            self.ts = t
            return frame, t

    def close(self) -> None:
        try:
            self.cap.release()
        except Exception:
            pass


class UploadController:
    """Playback state of one uploaded-video camera.

    The API thread only queues commands (command()); the camera worker thread applies them between frames,
    so the video file, decoder and tracking state are only ever touched by one thread and only one
    processing loop can exist per camera.
    """

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.store = VideoStore(camera_id)
        found = self.store.current()
        self.meta, self.path = found if found else (None, None)
        self.state = "ready" if self.meta else "empty"
        self.message = ""
        self.commands: queue.Queue = queue.Queue()
        self.upload_lock = threading.Lock()
        self.speed = 1.0
        self.run = 0
        self.session: str | None = None
        self.session_started: float | None = None
        self.position = 0.0
        self.frames_analysed = 0
        self.ended_early = False
        self.recent: deque = deque()  # (wall, video t) of analysed frames, last 3 s
        self.timeline: list[dict] = []
        self.sample_every = 1.0
        self.anchor: tuple[float, float] | None = None  # (wall, video t) for real-time pacing
        self.model_loading = False

    # ---------------------------------------------------------------- API side
    def command(self, action: str, timeout: float = 8.0, **kw) -> dict:
        done, box = threading.Event(), {}
        self.commands.put((action, kw, done, box))
        if not done.wait(timeout):
            return {"ok": False, "error": "The video worker did not answer in time. Try again in a moment."}
        return box["result"]

    # ---------------------------------------------------------------- worker side
    def take(self, wait: float) -> list:
        out = []
        try:
            out.append(self.commands.get(timeout=wait) if wait > 0 else self.commands.get_nowait())
            while True:
                out.append(self.commands.get_nowait())
        except queue.Empty:
            pass
        return out

    def new_session(self) -> None:
        self.run += 1
        # unique across server restarts, so one run's tracks never mix with another's
        self.session = f"{self.video_key()[:8]}-{self.run}-{uuid.uuid4().hex[:6]}" if self.meta else None
        self.session_started = time.time()
        self.position = 0.0
        self.frames_analysed = 0
        self.ended_early = False
        self.recent.clear()
        self.timeline = []
        self.sample_every = 1.0
        self.anchor = None

    def video_key(self) -> str:
        """Identity of the video's content (SHA-256 prefix); older uploads fall back to their file id."""
        return (self.meta or {}).get("video_id") or (self.meta or {}).get("id") or ""

    def analysed(self, wall: float, t: float) -> None:
        self.position = t
        self.frames_analysed += 1
        self.recent.append((wall, t))
        # rate over the last 3 s, but always over at least the last two frames (Dense crowd: seconds per frame)
        while len(self.recent) > 2 and wall - self.recent[0][0] > 3.0:
            self.recent.popleft()

    def rates(self) -> tuple[float, float | None]:
        """(frames analysed per second, video seconds per wall second) over the last few seconds."""
        if self.state != "processing" or len(self.recent) < 2:
            return 0.0, None
        (w0, t0), (w1, t1) = self.recent[0], self.recent[-1]
        span = w1 - w0
        if span <= 0.2:
            return 0.0, None
        return (len(self.recent) - 1) / span, (t1 - t0) / span

    def add_sample(self, sample: dict) -> None:
        if self.timeline and sample["vt"] - self.timeline[-1]["vt"] < self.sample_every:
            return
        self.timeline.append(sample)
        if len(self.timeline) > 6000:  # very long videos: keep the whole timeline at half the detail
            self.timeline = self.timeline[::2]
            self.sample_every *= 2

    def info(self) -> dict:
        m = self.meta or {}
        fps, realtime = self.rates()
        duration = m.get("duration_s")
        progress = None
        if duration:
            progress = 1.0 if self.state == "completed" and not self.ended_early else min(1.0, self.position / duration)
        return {"state": self.state, "message": self.message, "file": m.get("name"), "container": m.get("container"),
                "codec": m.get("codec"), "size_bytes": m.get("size_bytes"), "width": m.get("width"),
                "height": m.get("height"), "video_fps": m.get("fps"), "duration_s": duration,
                "position_s": round(self.position, 2), "progress": None if progress is None else round(progress, 4),
                "analysis_fps": round(fps, 1), "realtime": None if realtime is None else round(realtime, 2),
                "speed": self.speed, "frames_analysed": self.frames_analysed, "session": self.session,
                "model_loading": self.model_loading,
                "session_started": self.session_started, "uploaded_at": m.get("uploaded_at"),
                "video_id": self.video_key() or None, "max_upload_mb": config.MAX_UPLOAD_MB, "accepted": ACCEPTED}
