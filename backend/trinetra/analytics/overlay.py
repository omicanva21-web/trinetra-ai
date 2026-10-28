"""Draws the analysis onto each frame: heat overlay, zones, counting lines, tracked people with
their trails and ID tags, and a status bar. Every annotated frame is also what the evidence clips show."""
from __future__ import annotations

import time

import cv2
import numpy as np

from .tracks import track_color_bgr

COLORS = {"LOW": (80, 175, 76), "MEDIUM": (0, 165, 255), "HIGH": (40, 40, 230)}  # BGR
FONT = cv2.FONT_HERSHEY_SIMPLEX
WHITE, BLACK, GREY = (255, 255, 255), (0, 0, 0), (170, 170, 170)


class HeatLayer:
    """Short-memory heatmap of foot points (decays over ~3 s)."""

    def __init__(self, decay: float = 0.92, scale: int = 4):
        self.decay, self.scale, self.acc = decay, scale, None

    def update(self, frame_shape, feet) -> np.ndarray:
        h, w = frame_shape[0] // self.scale, frame_shape[1] // self.scale
        if self.acc is None or self.acc.shape != (h, w):
            self.acc = np.zeros((h, w), np.float32)
        self.acc *= self.decay
        for x, y in feet:
            cv2.circle(self.acc, (int(x / self.scale), int(y / self.scale)), 6, 1.0, -1)
        return self.acc


def _label(img, text, x, y, bg, fg=BLACK, scale=0.5, thick=1, pad=4):
    """Filled tag with text; (x, y) is the tag's bottom-left corner. Kept inside the frame."""
    (tw, th), base = cv2.getTextSize(text, FONT, scale, thick)
    h, w = img.shape[:2]
    x = int(min(max(0, x), max(0, w - tw - 2 * pad)))
    y = int(min(max(th + 2 * pad, y), h))
    cv2.rectangle(img, (x, y - th - 2 * pad), (x + tw + 2 * pad, y), bg, -1)
    cv2.putText(img, text, (x + pad, y - pad - base // 2), FONT, scale, fg, thick, cv2.LINE_AA)


def _arrow_line(img, a, b, label, s):
    a, b = tuple(int(v) for v in a), tuple(int(v) for v in b)
    cv2.line(img, a, b, BLACK, max(4, int(6 * s)), cv2.LINE_AA)
    cv2.line(img, a, b, (255, 230, 80), max(2, int(3 * s)), cv2.LINE_AA)
    d = np.array(b, float) - np.array(a, float)
    n = np.array([-d[1], d[0]]) / max(np.linalg.norm(d), 1.0)  # points to the IN side
    m = (np.array(a, float) + np.array(b, float)) / 2
    tail, tip = tuple((m - n * 18 * s).astype(int)), tuple((m + n * 34 * s).astype(int))
    cv2.arrowedLine(img, tail, tip, (255, 230, 80), max(2, int(3 * s)), cv2.LINE_AA, tipLength=0.4)
    _label(img, "IN", tip[0] + 4, tip[1] + 8, (255, 230, 80), BLACK, 0.45 * s, 1)
    h = img.shape[0]
    low = a if a[1] >= b[1] else b  # counter under the lower end (people's tags sit above them)
    y = low[1] + int(28 * s) if low[1] + int(30 * s) < h else min(a[1], b[1]) - int(8 * s)
    _label(img, label, low[0] - int(40 * s), y, (40, 40, 40), (255, 230, 80), 0.5 * s, 1)


def draw(frame, dets, state, heat: HeatLayer, zone_polys: dict, registry=None, options: dict | None = None,
         focus_id: int | None = None, hud: dict | None = None) -> np.ndarray:
    options = options or {}
    out = frame.copy()
    h, w = out.shape[:2]
    s = max(0.6, min(2.0, w / 1100))  # text and line scale for this resolution

    if options.get("heatmap", True):
        acc = heat.update(frame.shape, [d["foot"] for d in dets if d["cls"] == "person" and "foot" in d])
        blur = cv2.GaussianBlur(acc, (0, 0), 6)
        if blur.max() > 0.05:
            norm = np.clip(blur / max(blur.max(), 1.0), 0, 1)
            colour = cv2.resize(cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_JET), (w, h))
            mask = cv2.resize(norm, (w, h))[..., None] * 0.35
            out = (out * (1 - mask) + colour * mask).astype(np.uint8)

    for z in state["zones"]:
        poly = zone_polys[z["id"]].astype(np.int32)
        c = COLORS[z["level"]]
        cv2.polylines(out, [poly], True, c, 3 if z["level"] != "LOW" else 2, cv2.LINE_AA)
        x, y = poly.reshape(-1, 2).min(axis=0)
        if z["kind"] == "crowd" and z["density"] is not None:
            text = f"{z['name']}  {z['density']:.2f}/m2"
            if z["eta_s"] is not None:
                e = int(z["eta_s"])
                text += f"  ETA {e // 60}:{e % 60:02d}"
        else:
            text = f"{z['name']}  {z['count']} inside"
        _label(out, text, x + 2, y + int(24 * s), c, WHITE, 0.5 * s, 1)

    if registry is not None:
        for ln in registry.lines:
            _arrow_line(out, ln.a_draw, ln.b_draw, f"{ln.name}  IN {ln.count_in}  OUT {ln.count_out}", s)

    now_t = registry.t if registry is not None else 0.0
    crowd = (options or {}).get("model") == "crowd"  # dozens of small people: thin boxes, ID-only tags
    for d in sorted(dets, key=lambda d: d.get("id") == focus_id):  # focused person drawn last, on top
        x1, y1, x2, y2 = (int(v) for v in d["box"])
        tid = d.get("id")
        if tid is None:  # not confirmed yet: thin grey box
            cv2.rectangle(out, (x1, y1), (x2, y2), GREY, 1)
            continue
        col = track_color_bgr(tid)
        tr = registry.active.get(tid) if registry is not None else None
        focused = focus_id is not None and tid == focus_id
        dim = focus_id is not None and not focused
        restricted = bool(tr and any(k == "restricted" for _, k in tr.get("zones_now", [])))

        if tr is not None and options.get("trails", True) and (focused or not crowd):  # crowds: trails only when followed
            window = 1e9 if focused else 4.0
            pts = [(int(px), int(py)) for t, px, py in tr["path"] if now_t - t <= window]
            for i in range(1, len(pts)):
                fade = i / len(pts)
                th = max(1, int((4 if focused else 3) * s * fade + 0.5))
                cv2.line(out, pts[i - 1], pts[i], col if not dim else GREY, th, cv2.LINE_AA)
        if focused:
            cv2.rectangle(out, (x1 - 3, y1 - 3), (x2 + 3, y2 + 3), WHITE, max(2, int(2 * s)))
        cv2.rectangle(out, (x1, y1), (x2, y2), (40, 40, 230) if restricted else (col if not dim else GREY),
                      max(1 if crowd else 2, int((3 if focused or restricted else (1 if crowd else 2)) * s)))
        if dim:
            continue
        text = f"#{tid}"
        if crowd and not focused:
            _label(out, text, x1, y1 - 1, col, BLACK, 0.36 * s, 1, pad=2)
            continue
        if tr is not None:
            text += f"  {now_t - tr['first_t']:.0f}s"
            if tr.get("speed") is not None and d["cls"] == "person":
                text += f"  {tr['speed']:.1f}m/s"
        if d["cls"] == "vehicle":
            text += "  vehicle"
        _label(out, text, x1, y1 - 2, col, BLACK, 0.48 * s, 1)

    if hud:
        clock = hud.get("clock") or time.strftime("%H:%M:%S")  # uploaded video: position in the video
        tracking = state.get("tracking", {})
        parts = [hud.get("tag", "LIVE"), clock, f"{hud.get('fps', 0):.1f} fps",
                 f"tracking {tracking.get('active_count', 0)}", f"unique {tracking.get('unique', 0)}"]
        text = "   ".join(parts)
        (tw, th), _ = cv2.getTextSize(text, FONT, 0.5 * s, 1)
        x0 = w - tw - int(30 * s)
        overlay = out.copy()
        cv2.rectangle(overlay, (x0 - 8, 4), (w - 4, th + int(16 * s)), BLACK, -1)
        out = cv2.addWeighted(overlay, 0.6, out, 0.4, 0)
        dot = (40, 40, 230) if hud.get("tag") == "LIVE" else (180, 180, 180)
        cv2.circle(out, (x0 + 4, th // 2 + int(10 * s)), max(3, int(5 * s)), dot, -1, cv2.LINE_AA)
        cv2.putText(out, text, (x0 + int(14 * s), th + int(9 * s)), FONT, 0.5 * s, WHITE, 1, cv2.LINE_AA)
    return out
