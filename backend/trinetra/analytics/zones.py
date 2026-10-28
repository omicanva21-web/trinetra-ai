"""Per-zone measurements: count, density, speed, crowd pressure, dwell, Crush Clock."""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from .crushclock import DensityHistory, time_to_danger
from .geometry import FloorCalibration, point_in_polygon, polygon_area


class TrackMotion:
    """Keeps recent floor positions per track ID and returns velocities in m/s."""

    def __init__(self, window_s: float = 1.0, forget_s: float = 2.0):
        self.window_s = window_s
        self.forget_s = forget_s
        self.tracks: dict[int, deque] = {}

    def update(self, t: float, positions: dict[int, tuple[float, float]]) -> dict[int, tuple[float, float]]:
        for tid, (x, y) in positions.items():
            self.tracks.setdefault(tid, deque()).append((t, x, y))
        velocities = {}
        for tid in list(self.tracks):
            hist = self.tracks[tid]
            while hist and t - hist[0][0] > self.window_s * 1.5:
                hist.popleft()
            if not hist or t - hist[-1][0] > self.forget_s:
                del self.tracks[tid]
                continue
            t0, x0, y0 = hist[0]
            t1, x1, y1 = hist[-1]
            if tid in positions and t1 - t0 >= 0.4 * self.window_s:
                velocities[tid] = ((x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0))
        return velocities


class ZoneMonitor:
    """One configured zone on one camera."""

    def __init__(self, cfg: dict, calib: FloorCalibration | None):
        self.cfg = cfg
        self.id = cfg["id"]
        self.name = cfg.get("name", self.id)
        self.kind = cfg.get("kind", "crowd")  # crowd | restricted
        self.classes = set(cfg.get("classes", ["person"] if self.kind == "crowd" else ["person", "vehicle"]))
        self.polygon_px = np.asarray(cfg["polygon"], dtype=np.float32).reshape(-1, 1, 2)
        if cfg.get("area_m2"):
            self.area_m2 = float(cfg["area_m2"])
        elif calib is not None:
            self.area_m2 = polygon_area(calib.to_floor(self.polygon_px.reshape(-1, 2)))
        else:
            self.area_m2 = None  # density unavailable without calibration or area_m2
        self.history = DensityHistory()
        self.rho_ema = 0.0
        self.speed_baseline = None
        self.last_t = None
        self.entered_at: dict[int, float] = {}
        self.last_inside: dict[int, float] = {}

    def contains(self, foot_px) -> bool:
        return point_in_polygon(self.polygon_px, foot_px)

    def update(self, t: float, inside: list[dict], velocities: dict, profile: dict) -> dict:
        dt = 0.0 if self.last_t is None else max(0.0, t - self.last_t)
        self.last_t = t
        n = len(inside)

        # Density, smoothed with a ~2 s time constant so one missed box does not jump the number.
        rho = None
        if self.area_m2:
            rho_raw = n / self.area_m2
            alpha = 1.0 if dt == 0 else 1.0 - math.exp(-dt / 2.0)
            self.rho_ema += alpha * (rho_raw - self.rho_ema)
            rho = self.rho_ema
            self.history.add(t, rho)

        # Speed and Helbing crowd pressure from tracked velocities inside the zone.
        vs = np.array([velocities[d["id"]] for d in inside if d.get("id") in velocities], dtype=np.float64)
        speed = pressure = None
        surge_ratio = 1.0
        if len(vs) >= 2:
            speeds = np.linalg.norm(vs, axis=1)
            speed = float(np.median(speeds))
            if self.speed_baseline is None:
                self.speed_baseline = max(speed, 0.3)
            surge_ratio = speed / max(self.speed_baseline, 0.3)
            if surge_ratio < 1.5:  # do not let a surge become the new "normal"
                a = 1.0 - math.exp(-dt / 20.0) if dt else 0.0
                self.speed_baseline += a * (speed - self.speed_baseline)
            if rho is not None and len(vs) >= 3:
                var = float(np.mean(np.sum((vs - vs.mean(axis=0)) ** 2, axis=1)))
                pressure = rho * var

        # Dwell time per track, tolerating a 1 s gap from a missed detection.
        now_ids = {d["id"] for d in inside if d.get("id") is not None}
        for tid in now_ids:
            self.entered_at.setdefault(tid, t)
            self.last_inside[tid] = t
        for tid in list(self.last_inside):
            if t - self.last_inside[tid] > 1.0:
                self.last_inside.pop(tid)
                self.entered_at.pop(tid, None)
        max_dwell = max((t - self.entered_at[i] for i in now_ids if i in self.entered_at), default=0.0)

        clock = {"eta_s": None, "slope_per_s": None, "r2": None, "trend": "unknown"}
        if rho is not None and self.kind == "crowd":
            clock = time_to_danger(self.history.samples, rho, profile["density_danger"])

        return {
            "count": n,
            "density": None if rho is None else round(rho, 3),
            "area_m2": None if self.area_m2 is None else round(self.area_m2, 2),
            "speed": None if speed is None else round(speed, 3),
            "surge_ratio": round(surge_ratio, 2),
            "pressure": None if pressure is None else round(pressure, 4),
            "max_dwell_s": round(max_dwell, 1),
            "has_vehicle": any(d["cls"] == "vehicle" for d in inside),
            "ids": sorted(now_ids)[:8],
            "eta_s": None if clock["eta_s"] is None else round(clock["eta_s"], 1),
            "trend": clock["trend"],
            "slope_per_min": None if clock["slope_per_s"] is None else round(clock["slope_per_s"] * 60, 3),
        }
