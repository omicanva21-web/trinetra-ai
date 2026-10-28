"""Track registry: turns tracker IDs into analytics.

For every tracked person or vehicle it keeps: the path of their feet, time in view, distance walked,
speed, the zones they are in (and for how long), the zones they visited, and counting-line crossings.
When a track has not been seen for `finalize_s` seconds it is closed and summarised (for the database).

Speeds and distances are in metres when the camera is floor-calibrated. Without calibration they are
estimated for people from their box height (a person is taken as 1.7 m tall) and marked "est.".
"""
from __future__ import annotations

import colorsys
import math
from collections import deque

import numpy as np

from .geometry import FloorCalibration

PERSON_HEIGHT_M = 1.7


def track_color_bgr(tid: int) -> tuple[int, int, int]:
    """Same colour as the dashboard's hsl((id * 137.508) % 360, 85%, 55%)."""
    r, g, b = colorsys.hls_to_rgb((tid * 137.508) % 360 / 360.0, 0.55, 0.85)
    return int(b * 255), int(g * 255), int(r * 255)


def _side(a, b, p) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def segments_cross(p0, p1, a, b) -> bool:
    return _side(a, b, p0) * _side(a, b, p1) < 0 and _side(p0, p1, a) * _side(p0, p1, b) < 0


class CountingLine:
    """A line A→B. Moving from its negative side to its positive side counts as IN; the arrow drawn
    on the video points to the IN side. A person must be clearly on one side (outside a small band
    around the line) before and after, so someone standing on the line is never counted twice."""

    def __init__(self, cfg: dict, diag: float):
        self.id, self.name = cfg["id"], cfg.get("name", cfg["id"])
        a, b = np.asarray(cfg["points"][0], float), np.asarray(cfg["points"][1], float)
        self.a_draw, self.b_draw = a, b
        ext = (b - a) * 0.05  # extended 5% each way so feet on the frame edge still cross it
        self.a, self.b = a - ext, b + ext
        self.length = max(float(np.linalg.norm(b - a)), 1.0)
        self.margin = max(6.0, 0.015 * diag)
        self.count_in = self.count_out = 0

    def side(self, p) -> int:
        sd = _side(self.a, self.b, p) / self.length
        return 0 if abs(sd) < self.margin else (1 if sd > 0 else -1)


class TrackRegistry:
    def __init__(self, size: tuple[int, int], calib: FloorCalibration | None, zones: list, lines_cfg: list[dict],
                 finalize_s: float = 2.0, min_duration_s: float = 1.0, estimate_speed: bool = True):
        self.w, self.h = size
        self.estimate_speed = estimate_speed  # off for high-angle crowds: body height says nothing about metres there
        self.calib, self.zones = calib, zones
        self.lines = [CountingLine(c, math.hypot(self.w, self.h)) for c in lines_cfg]
        self.finalize_s, self.min_duration_s = finalize_s, min_duration_s
        self.active: dict[int, dict] = {}
        self.finished: deque = deque(maxlen=200)
        self.unique = self.finished_count = 0
        self.dwell_sum = 0.0
        self.t = 0.0

    # ---------------------------------------------------------------- geometry helpers
    def _metres_per_px(self, tr: dict) -> float | None:
        if tr["cls"] != "person" or not self.estimate_speed:
            return None
        h = tr["box"][3] - tr["box"][1]
        return PERSON_HEIGHT_M / h if h > 10 else None

    def _step_m(self, tr: dict, p0, p1) -> tuple[float | None, bool]:
        """Distance between two foot points in metres, and whether it is an estimate."""
        if self.calib is not None:
            f = self.calib.to_floor([p0, p1])
            return float(np.linalg.norm(f[1] - f[0])), False
        mpp = self._metres_per_px(tr)
        return (float(math.dist(p0, p1)) * mpp, True) if mpp else (None, True)

    # ---------------------------------------------------------------- per frame
    def update(self, t: float, wall: float, dets: list[dict]) -> list[dict]:
        self.t = t
        events = []
        for d in dets:
            tid = d.get("id")
            if tid is None:
                continue
            x, y = d.get("foot") or ((d["box"][0] + d["box"][2]) / 2, d["box"][3])
            tr = self.active.get(tid)
            if tr is None:
                tr = self.active[tid] = {
                    "id": tid, "cls": d["cls"], "first_t": t, "first_wall": wall, "path": deque(maxlen=400),
                    "arch": [], "dist": 0.0, "est": self.calib is None, "visited": [], "zone_since": {},
                    "crossings": [], "line_side": {}, "counted": False, "speed": None, "conf": d["conf"],
                    "box": d["box"], "max_speed": 0.0,
                }
            prev = tr["path"][-1] if tr["path"] else None
            tr.update(last_t=t, last_wall=wall, box=d["box"], conf=d["conf"], cls=d["cls"])
            if prev is None or t - prev[0] >= 0.1:
                tr["path"].append((t, x, y))
                if prev is not None:
                    step, _ = self._step_m(tr, prev[1:], (x, y))
                    if step is not None and step > 0.04:  # ignore detector jitter
                        tr["dist"] += step
                if not tr["arch"] or t - tr["arch"][-1][0] >= 0.5:
                    tr["arch"].append((t, round(x / self.w, 4), round(y / self.h, 4)))
                    if len(tr["arch"]) > 240:  # keep long stays bounded: thin out evenly
                        tr["arch"] = tr["arch"][::2]

            # speed over the last second (robust to per-frame jitter)
            old = next((p for p in tr["path"] if t - p[0] <= 1.2), None)
            if old is not None and t - old[0] >= 0.4:
                step, _ = self._step_m(tr, old[1:], (x, y))
                if step is not None:
                    tr["speed"] = step / (t - old[0])
                    tr["max_speed"] = max(tr["max_speed"], tr["speed"])

            # zones the feet are in, with time in each
            now = [z for z in self.zones if d["cls"] in z.classes and z.contains((x, y))]
            names = {z.name for z in now}
            for name in list(tr["zone_since"]):
                if name not in names:
                    del tr["zone_since"][name]
            for z in now:
                tr["zone_since"].setdefault(z.name, t)
                if z.name not in tr["visited"]:
                    tr["visited"].append(z.name)
            tr["zones_now"] = [(z.name, z.kind) for z in now]

            # counting lines: count when the feet move from clearly one side to clearly the other
            for line in self.lines:
                side = line.side((x, y))
                if side == 0:
                    continue
                last = tr["line_side"].get(line.id)
                if last is not None and last[0] != side and segments_cross(last[1], (x, y), line.a, line.b):
                    direction = "in" if last[0] < 0 else "out"
                    if direction == "in":
                        line.count_in += 1
                    else:
                        line.count_out += 1
                    tr["crossings"].append({"line": line.name, "dir": direction})
                    events.append({"type": "crossing", "line_id": line.id, "line_name": line.name,
                                   "direction": direction, "track_id": tid, "wall": wall, "t": round(t, 2)})
                tr["line_side"][line.id] = (side, (x, y))

            if not tr["counted"] and t - tr["first_t"] >= self.min_duration_s:
                tr["counted"] = True
                self.unique += 1

        for tid, tr in list(self.active.items()):
            if t - tr["last_t"] > self.finalize_s:
                del self.active[tid]
                summary = self._summary(tr)
                if summary["duration_s"] >= self.min_duration_s:
                    self.finished.append(summary)
                    self.finished_count += 1
                    self.dwell_sum += summary["duration_s"]
                    events.append({"type": "track_done", **summary})
        return events

    def discard(self, tid: int) -> None:
        """Forget a track the tracker found to be a static object, not a person."""
        tr = self.active.pop(tid, None)
        if tr is not None and tr["counted"]:
            self.unique -= 1

    def _summary(self, tr: dict) -> dict:
        duration = tr["last_t"] - tr["first_t"]
        return {"track_id": tr["id"], "cls": tr["cls"], "started_wall": tr["first_wall"],
                "ended_wall": tr["last_wall"], "started_t": round(tr["first_t"], 2), "ended_t": round(tr["last_t"], 2),
                "duration_s": round(duration, 1),
                "distance_m": round(tr["dist"], 2), "estimated": tr["est"],
                "avg_speed": round(tr["dist"] / duration, 2) if duration > 0 else 0.0,
                "max_speed": round(tr["max_speed"], 2), "zones": list(tr["visited"]),
                "crossings": list(tr["crossings"]), "path": [[x, y] for _, x, y in tr["arch"]]}

    # ---------------------------------------------------------------- views
    def snapshot(self, focus_id: int | None = None, limit: int = 60) -> dict:
        t = self.t
        rows = []
        for tr in sorted(self.active.values(), key=lambda r: r["first_t"]):
            seen = t - tr["last_t"] < 0.6
            speed = tr["speed"]
            state = "hidden" if not seen else ("moving" if speed is not None and speed >= 0.3 else "still")
            x, y = tr["path"][-1][1:] if tr["path"] else (0, 0)
            rows.append({"id": tr["id"], "cls": tr["cls"], "age_s": round(t - tr["first_t"], 1),
                         "zones": [{"name": n, "kind": k, "s": round(t - tr["zone_since"].get(n, t), 1)}
                                   for n, k in tr.get("zones_now", [])] if seen else [],
                         "speed": None if speed is None else round(speed, 2), "est": tr["est"],
                         "dist": round(tr["dist"], 1) if self.calib is not None or self.estimate_speed else None,
                         "state": state, "conf": round(tr["conf"], 2),
                         "pos": [round(x / self.w, 3), round(y / self.h, 3)]})
        visible = [r for r in rows if r["state"] != "hidden"]
        return {"active": rows[-limit:], "active_count": len(visible),
                "people_tracked": sum(1 for r in visible if r["cls"] == "person"),
                "unique": self.unique, "finished": self.finished_count,
                "avg_dwell_s": round(self.dwell_sum / self.finished_count, 1) if self.finished_count else None,
                "longest_s": max((r["age_s"] for r in visible), default=None),
                "lines": [{"id": ln.id, "name": ln.name, "in": ln.count_in, "out": ln.count_out} for ln in self.lines],
                "focus": focus_id}

    def paths(self, recent: int = 60) -> dict:
        def thin(pts, n=80):
            step = max(1, len(pts) // n)
            return pts[::step] + ([pts[-1]] if pts and (len(pts) - 1) % step else [])

        active = [{"id": tr["id"], "cls": tr["cls"], "age_s": round(self.t - tr["first_t"], 1),
                   "path": thin([[round(x / self.w, 4), round(y / self.h, 4)] for _, x, y in tr["path"]])}
                  for tr in self.active.values()]
        return {"active": active, "finished": list(self.finished)[-recent:]}
