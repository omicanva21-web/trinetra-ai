"""Measure a clip: per-second metrics CSV, Crush Clock lead time, and tracking results.

Usage (from the project folder):
  python eval/lead_time.py --camera cam2 --profile station             # uses the camera's source in site.json
  python eval/lead_time.py --camera cam2 --video clips/platform.mp4    # override the source
  python eval/lead_time.py --camera cam3 --mock --seconds 150          # simulated scene (plumbing check only)

Runs as fast as the detector allows (not real time) and uses the video's own timestamps.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from trinetra.analytics.pipeline import Analyzer  # noqa: E402
from trinetra.analytics.tracks import TrackRegistry  # noqa: E402
from trinetra.siteconfig import resolve  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", required=True)
    ap.add_argument("--profile", default="station")
    ap.add_argument("--video")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--fps", type=float, default=10, help="analysed frames per second of video")
    ap.add_argument("--detector", default="auto", choices=["auto", "yolo", "yolox"])
    ap.add_argument("--out", default="eval/metrics.csv")
    a = ap.parse_args()

    site = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
    profiles = json.loads((ROOT / "config" / "profiles.json").read_text(encoding="utf-8"))
    cam_raw = next(c for c in site["cameras"] if c["id"] == a.camera)
    p = profiles[a.profile]
    an = reg = None

    def frames():
        if a.mock:
            from trinetra.mock_scene import MockScene
            scene = MockScene(resolve(cam_raw, MockScene.W, MockScene.H))
            t = 0.0
            while t <= a.seconds:
                yield round(t, 2), *scene.step(t)
                t += 1 / a.fps
            return
        import cv2
        from trinetra.detector import make_detector
        src = a.video or cam_raw["source"]
        cap = cv2.VideoCapture(int(src) if str(src).isdigit() else str(ROOT / src) if "://" not in src else src)
        vfps = cap.get(cv2.CAP_PROP_FPS) or 25
        step = max(1, round(vfps / a.fps))
        det, err = make_detector(a.detector)
        if det is None:
            raise SystemExit(err)
        print(f"detector: {det.name}")
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok or i / vfps > a.seconds:
                return
            if i % step == 0:
                yield i / vfps, frame, det.detect(frame, i / vfps)
            i += 1

    rows, first_alert, first_high, crossed = [], None, None, None
    crossings, done = [], []
    started = time.time()
    for t, frame, dets in frames():
        if an is None:  # zones are stored as fractions of the frame: fit them to this video's size
            h, w = frame.shape[:2]
            cfg = resolve(cam_raw, w, h)
            an = Analyzer(cfg, p)
            reg = TrackRegistry((w, h), an.calib, an.zones, cfg.get("lines", []))
        state, events = an.analyze(dets, t)
        for ev in reg.update(t, started + t, dets):
            (crossings if ev["type"] == "crossing" else done).append(ev)
        for e in events:
            if e["incident"]["kind"].startswith("crowd") and e["action"] in ("opened", "reopened") and first_alert is None:
                first_alert = t
            if e["incident"]["kind"].startswith("crowd") and e["incident"]["level"] == "HIGH" and first_high is None:
                first_high = t
        for z in state["zones"]:
            if z["kind"] != "crowd":
                continue
            if crossed is None and z["density"] is not None and z["density"] >= p["density_danger"]:
                crossed = t
            if not rows or t - rows[-1]["t"] >= 1.0:
                rows.append({"t": round(t, 1), "zone": z["id"], "count": z["count"], "density": z["density"],
                             "eta_s": z["eta_s"], "trend": z["trend"], "speed": z["speed"],
                             "pressure": z["pressure"], "score": z["score"], "level": z["level"],
                             "tracked": len([d for d in dets if d.get("id") is not None])})

    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["t"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {out}")
    print(f"first crowd alert at {first_alert} s, first HIGH at {first_high} s, density crossed danger at {crossed} s")
    if crossed is not None and first_alert is not None:
        print(f"lead time: {crossed - first_alert:.1f} s (MEDIUM), "
              f"{(crossed - first_high) if first_high is not None else float('nan'):.1f} s (HIGH); a plain threshold gives 0 s")
    elif crossed is None:
        print("density never reached the danger line in this clip: no lead time to report")
    if reg is not None:
        snap = reg.snapshot()
        people = [d for d in done if d["cls"] == "person"]
        avg = sum(d["duration_s"] for d in people) / len(people) if people else 0
        print(f"tracking: {snap['unique']} unique tracks (≥1 s), {len(people)} people finished, "
              f"average time in view {avg:.1f} s")
        for ln in snap["lines"]:
            print(f"  line {ln['name']}: IN {ln['in']}  OUT {ln['out']}")


if __name__ == "__main__":
    main()
