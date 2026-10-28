"""Snapshots (JPEG) and short H.264 clips that browsers can play.

OpenCV's pip build cannot write H.264, so clips are piped as raw frames into ffmpeg: the system ffmpeg
if it is on PATH, otherwise the one bundled with the `imageio-ffmpeg` pip package (works on Windows).
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import cv2

from . import config


def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class Evidence:
    def __init__(self, folder: Path | None = None, pre_s: float = 5.0, post_s: float = 5.0, width: int = 640):
        self.folder = Path(folder or config.EVIDENCE_DIR)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.width, self.pre_s, self.post_s = width, pre_s, post_s
        self.buffer: deque = deque()  # (monotonic time, small frame)
        self.jobs: list[dict] = []
        self.ffmpeg = find_ffmpeg()

    def _small(self, frame):
        h, w = frame.shape[:2]
        nw = min(self.width, w) // 2 * 2
        nh = int(h * nw / w) // 2 * 2  # libx264 needs even sizes
        return frame if (nw, nh) == (w, h) else cv2.resize(frame, (nw, nh))

    def push(self, frame, now: float | None = None) -> None:
        """Call once per analysed frame; finished clips are written in a background thread.
        `now` is the frame's time; uploaded videos pass their own timeline so clips play at the video's speed."""
        now, small = (time.monotonic() if now is None else now), self._small(frame)
        self.buffer.append((now, small))
        while self.buffer and now - self.buffer[0][0] > self.pre_s:
            self.buffer.popleft()
        done = []
        for job in self.jobs:
            job["frames"].append((now, small))
            if now >= job["until"]:
                done.append(job)
        for job in done:
            self.jobs.remove(job)
            threading.Thread(target=self._write_clip, args=(job,), daemon=True).start()

    def snapshot(self, incident_id: str, frame) -> str:
        path = self.folder / f"{incident_id}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return str(path)

    def start_clip(self, incident_id: str, on_done) -> bool:
        if not self.ffmpeg or any(j["id"] == incident_id for j in self.jobs):
            return False
        now = self.buffer[-1][0] if self.buffer else time.monotonic()
        self.jobs.append({"id": incident_id, "frames": list(self.buffer), "until": now + self.post_s,
                          "on_done": on_done})
        return True

    def reset(self) -> None:
        """The timeline restarts (uploaded video restarted or stopped): write pending clips with what they have."""
        for job in self.jobs:
            threading.Thread(target=self._write_clip, args=(job,), daemon=True).start()
        self.jobs = []
        self.buffer.clear()

    def _write_clip(self, job: dict) -> None:
        frames = job["frames"]
        if len(frames) < 2:
            return
        fps = max(1.0, min(30.0, (len(frames) - 1) / max(frames[-1][0] - frames[0][0], 1e-3)))  # real speed
        h, w = frames[0][1].shape[:2]
        path = self.folder / f"{job['id']}.mp4"
        cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{w}x{h}", "-r", f"{fps:.2f}", "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            for _, f in frames:
                if f.shape[:2] == (h, w):
                    proc.stdin.write(f.tobytes())
            proc.stdin.close()
            if proc.wait() == 0:
                job["on_done"](job["id"], str(path))
        except OSError:
            pass  # ffmpeg missing or broken: the snapshot is still there
