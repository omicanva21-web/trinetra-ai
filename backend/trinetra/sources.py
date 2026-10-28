"""Video sources: webcam / RTSP (always the newest frame), the browser's camera, video files, simulation."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from . import config

VIDEO_EXT = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v")


def describe(source: str) -> str:
    s = str(source)
    if s == "mock":
        return "simulated"
    if s == "browser":
        return "browser"
    if s == "upload":  # a video uploaded from the dashboard (see uploads.py)
        return "upload"
    if s.isdigit():
        return "webcam"
    if "://" in s:
        return "stream"
    return "file"


def resolve_path(source: str) -> str:
    p = Path(source)
    return str(p if p.is_absolute() else config.ROOT / p)


class LiveSource:
    """Webcam or RTSP/HTTP camera. A background thread keeps reading so we always analyse the newest
    frame; without it OpenCV's internal buffer makes the picture lag seconds behind reality."""

    kind = "live"

    def __init__(self, source: str, width: int = 1280, height: int = 720):
        self.source = source
        if source.isdigit():
            index = int(source)
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(index)
            if not cap.isOpened():  # fall back to the default backend
                cap = cv2.VideoCapture(index)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        else:
            cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open {'webcam ' + source if source.isdigit() else source} "
                               "(in use by another app, unplugged, or wrong index/URL)")
        self.cap = cap
        self.frame = None
        self.frame_time = 0.0
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 8.0  # cameras can take a few seconds to deliver the first frame
        while self.frame is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.frame is None:
            self.close()
            raise RuntimeError(f"no frames from {source} within 8 s")

    def _reader(self) -> None:
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame, self.frame_time = frame, time.monotonic()
            else:
                time.sleep(0.05)

    def read(self, t_wall: float):
        with self.lock:
            frame, age = self.frame, time.monotonic() - self.frame_time
        if frame is None or age > 3.0:
            raise RuntimeError("camera stopped sending frames")
        return frame, t_wall

    def close(self) -> None:
        self.running = False
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2.0)  # let the reader finish its read before the camera is released
        try:
            self.cap.release()
        except Exception:
            pass


class BrowserFrames:
    """Newest JPEG per camera, pushed by the dashboard over /ws/camera/{id} (the browser opens the webcam)."""

    def __init__(self):
        self.cond = threading.Condition()
        self.frames: dict[str, tuple[bytes, float, int]] = {}
        self.senders: dict[str, int] = {}

    def put(self, camera_id: str, jpeg: bytes) -> None:
        with self.cond:
            seq = self.frames.get(camera_id, (b"", 0.0, 0))[2] + 1
            self.frames[camera_id] = (jpeg, time.monotonic(), seq)
            self.cond.notify_all()

    def connected(self, camera_id: str, delta: int) -> None:
        with self.cond:
            self.senders[camera_id] = max(0, self.senders.get(camera_id, 0) + delta)

    def wait(self, camera_id: str, after_seq: int, timeout: float):
        with self.cond:
            self.cond.wait_for(lambda: self.frames.get(camera_id, (b"", 0, 0))[2] > after_seq, timeout=timeout)
            return self.frames.get(camera_id)


BROWSER = BrowserFrames()


class BrowserSource:
    """Frames sent by the dashboard. read() returns (None, t) while no new frame arrives."""

    kind = "browser"

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.seq = 0
        self.last_frame_time = 0.0

    def read(self, t_wall: float, timeout: float = 0.5):
        got = BROWSER.wait(self.camera_id, self.seq, timeout)
        if not got or got[2] <= self.seq:
            return None, t_wall
        jpeg, arrived, self.seq = got
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return None, t_wall
        self.last_frame_time = arrived
        return frame, t_wall

    def close(self) -> None:
        pass


class FileSource:
    """A video file played at real speed; frames we cannot analyse in time are skipped; loops at the end.
    The analysis clock uses the video's own timestamps, so speeds stay correct even on a slow laptop."""

    kind = "file"

    def __init__(self, source: str):
        path = resolve_path(source)
        if not Path(path).exists():
            raise RuntimeError(f"video file not found: {path}")
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot decode video file: {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.idx, self.offset, self.t0 = 0, 0.0, None

    def read(self, t_wall: float):
        if self.t0 is None:
            self.t0 = t_wall
        target = int((t_wall - self.t0) * self.fps)
        while self.idx < target - 1 and self.cap.grab():
            self.idx += 1
        ok, frame = self.cap.read()
        if not ok:  # loop; keep the analysis clock increasing
            self.offset += self.idx / self.fps
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.idx, self.t0 = 0, t_wall
            ok, frame = self.cap.read()
            if not ok:
                raise RuntimeError("video file could not be read")
        self.idx += 1
        return frame, self.offset + self.idx / self.fps

    def close(self) -> None:
        self.cap.release()


class MockSource:
    """The simulated crowd. Supplies its own detections (no AI involved)."""

    kind = "mock"

    def __init__(self, camera_cfg: dict):
        from .mock_scene import MockScene

        self.scene = MockScene(camera_cfg)
        self.t0 = None
        self.dets = []

    def read(self, t_wall: float):
        if self.t0 is None:
            self.t0 = t_wall
        t = t_wall - self.t0
        frame, self.dets = self.scene.step(t)
        return frame, t

    def close(self) -> None:
        pass


def open_source(camera_cfg: dict):
    src = str(camera_cfg["source"])
    kind = describe(src)
    if kind == "simulated":
        return MockSource(camera_cfg)
    if kind == "browser":
        return BrowserSource(camera_cfg["id"])
    if kind == "upload":
        raise RuntimeError("uploaded-video cameras are read by the worker's upload loop")
    if kind == "file":
        return FileSource(src)
    return LiveSource(src)
