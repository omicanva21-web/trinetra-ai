"""Shared live state: latest frames per camera, 1-per-second metric history, WebSocket broadcast."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque

from fastapi import WebSocket

HISTORY_SECONDS = 30 * 60  # keep 30 minutes of 1 Hz samples per camera for the charts


class Hub:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[WebSocket] = set()
        self.frames: dict[str, bytes] = {}  # annotated JPEG, for the live tiles
        self.raw: dict[str, bytes] = {}  # clean JPEG, for drawing zones in Setup
        self.sizes: dict[str, tuple[int, int]] = {}
        self.states: dict[str, dict] = {}
        self.history: dict[str, deque] = {}
        self._last_sample: dict[str, float] = {}
        self.lock = threading.Lock()

    def set_frame(self, camera_id: str, jpeg: bytes, raw_jpeg: bytes | None = None, size=None) -> None:
        with self.lock:
            self.frames[camera_id] = jpeg
            if raw_jpeg is not None:
                self.raw[camera_id] = raw_jpeg
            if size:
                self.sizes[camera_id] = size

    def get_frame(self, camera_id: str, raw: bool = False) -> bytes | None:
        with self.lock:
            return (self.raw if raw else self.frames).get(camera_id)

    def forget(self, camera_id: str) -> None:
        with self.lock:
            for d in (self.frames, self.raw, self.sizes, self.states, self.history, self._last_sample):
                d.pop(camera_id, None)

    def _sample(self, state: dict) -> None:
        cid, now = state["camera_id"], time.time()
        if now - self._last_sample.get(cid, 0) < 1.0:
            return
        self._last_sample[cid] = now
        tr = state.get("tracking") or {}
        sample = {"ts": round(now, 1), "people": state["people"], "vehicles": state["vehicles"],
                  "score": state["score"], "tracked": tr.get("active_count", 0), "unique": tr.get("unique", 0),
                  "lines": {ln["id"]: [ln["in"], ln["out"]] for ln in tr.get("lines", [])},
                  "zones": {z["id"]: {"count": z["count"], "density": z["density"], "score": z["score"],
                                      "eta_s": z["eta_s"], "level": z["level"]} for z in state["zones"]}}
        self.history.setdefault(cid, deque(maxlen=HISTORY_SECONDS)).append(sample)

    def get_history(self, minutes: float) -> dict[str, list]:
        cutoff = time.time() - minutes * 60
        with self.lock:
            return {cid: [s for s in h if s["ts"] >= cutoff] for cid, h in self.history.items()}

    def publish(self, message: dict) -> None:
        """Safe to call from any thread."""
        if message.get("type") == "state":
            with self.lock:
                self.states[message["camera_id"]] = message
                self._sample(message)
        if self.loop is not None and self.clients:
            asyncio.run_coroutine_threadsafe(self._broadcast(json.dumps(message)), self.loop)

    async def _broadcast(self, text: str) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)
