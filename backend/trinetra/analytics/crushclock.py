"""Crush Clock: time until a zone reaches danger density, from its recent trend."""
from __future__ import annotations

from collections import deque

import numpy as np


class DensityHistory:
    """Rolling (time, density) samples for one zone."""

    def __init__(self, keep_s: float = 120.0, min_gap_s: float = 0.25):
        self.keep_s = keep_s
        self.min_gap_s = min_gap_s
        self.samples: deque[tuple[float, float]] = deque()

    def add(self, t: float, rho: float) -> None:
        if self.samples and t - self.samples[-1][0] < self.min_gap_s:
            return
        self.samples.append((t, rho))
        while self.samples and t - self.samples[0][0] > self.keep_s:
            self.samples.popleft()


def time_to_danger(
    samples,
    rho_now: float,
    rho_danger: float,
    window_s: float = 30.0,
    min_span_s: float = 10.0,
    min_r2: float = 0.5,
    min_slope: float | None = None,
    max_eta_s: float = 600.0,
) -> dict:
    """Least-squares trend over the last `window_s` seconds.

    Returns {eta_s, slope_per_s, r2, trend}. eta_s is None unless density is rising
    steadily (positive slope, enough history, a reasonable straight-line fit).
    """
    if rho_now >= rho_danger:
        return {"eta_s": 0.0, "slope_per_s": None, "r2": None, "trend": "critical"}
    if not samples:
        return {"eta_s": None, "slope_per_s": None, "r2": None, "trend": "unknown"}

    t_now = samples[-1][0]
    pts = np.array([(t, r) for t, r in samples if t >= t_now - window_s], dtype=np.float64)
    if len(pts) < 5 or pts[-1, 0] - pts[0, 0] < min_span_s:
        return {"eta_s": None, "slope_per_s": None, "r2": None, "trend": "warming_up"}

    t, r = pts[:, 0] - pts[0, 0], pts[:, 1]
    slope, intercept = np.polyfit(t, r, 1)
    fitted = slope * t + intercept
    ss_tot = float(np.sum((r - r.mean()) ** 2))
    r2 = 1.0 - float(np.sum((r - fitted) ** 2)) / ss_tot if ss_tot > 1e-12 else 0.0

    if min_slope is None:
        min_slope = rho_danger / 2000.0  # 0.0025 /m^2/s at a danger line of 5 /m^2
    if slope > min_slope and r2 >= min_r2:
        eta = (rho_danger - rho_now) / slope
        if eta > max_eta_s:  # a far-off countdown is noise, not a warning
            return {"eta_s": None, "slope_per_s": float(slope), "r2": r2, "trend": "slow_rise"}
        return {"eta_s": float(eta), "slope_per_s": float(slope), "r2": r2, "trend": "rising"}
    trend = "falling" if slope < -min_slope else "stable"
    return {"eta_s": None, "slope_per_s": float(slope), "r2": r2, "trend": trend}
