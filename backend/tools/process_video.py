"""Run Trinetra's tracking pipeline on a video file and save the annotated result.

It uses exactly the code Camera 4 uses (detector -> tracker -> zones/risk -> track registry -> overlay), with
Camera 4's zones and counting line from config/site.json, on the video's own timeline.

    python backend/tools/process_video.py my_video.mp4                       # Dense crowd mode, 3 frames/s
    python backend/tools/process_video.py my_video.mp4 --model fast --fps 10 # NanoDet, 10 frames/s

Writes <video>_tracked.mp4 (every analysed frame, at the analysed rate) and <video>_tracked.csv (one row per
analysed frame: time in the video, people detected, people with an ID, unique people so far, IN, OUT), and prints
a summary. Nothing is uploaded anywhere.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
_tmp = Path(tempfile.mkdtemp(prefix="trinetra_tool_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp / 'tool.db'}")  # keep the dashboard's database clean
os.environ.setdefault("TRINETRA_EVIDENCE", str(_tmp / "evidence"))
os.environ.setdefault("TRINETRA_UPLOADS", str(_tmp / "uploads"))

from trinetra import siteconfig  # noqa: E402
from trinetra.db import Store  # noqa: E402
from trinetra.evidence import find_ffmpeg  # noqa: E402
from trinetra.uploads import VideoReader, mmss, probe  # noqa: E402
from trinetra.worker import CameraWorker  # noqa: E402


class QuietHub:
    def set_frame(self, *a, **k):
        pass

    def publish(self, *a, **k):
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--model", choices=["fast", "accurate", "crowd"], default="crowd")
    ap.add_argument("--fps", type=float, default=3.0, help="frames analysed per second of video")
    ap.add_argument("--camera", default=None, help="camera whose zones/lines to use (default: the uploaded-video camera)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = Path(args.video)
    meta = probe(src)
    site = siteconfig.load_site()
    cam = next((c for c in site["cameras"] if c["id"] == args.camera), None) if args.camera else \
        next((c for c in site["cameras"] if str(c["source"]) == "upload"), None)
    cam = dict(cam or siteconfig.UPLOAD_CAMERA, id=(cam or {}).get("id", "cam4"))
    cam["source"] = "upload"
    cam["options"] = {**cam.get("options", {}), "model": args.model, "max_fps": args.fps}
    profiles = siteconfig.load_profiles()
    profile = profiles.get(site.get("profile", "station")) or next(iter(profiles.values()))
    worker = CameraWorker(cam, lambda: profile, QuietHub(), Store())
    worker._load_detector()
    if worker.detector is None:
        sys.exit(f"No detector: {worker.detector_name}")
    print(f"{src.name}: {meta['width']}x{meta['height']}, {meta['fps']} fps, {mmss(meta['duration_s'])}; "
          f"detector {worker.detector_name}; analysing {args.fps:g} frames per second of video")

    out = Path(args.out) if args.out else src.with_name(src.stem + "_tracked.mp4")
    w, h = meta["width"] // 2 * 2, meta["height"] // 2 * 2
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        sys.exit("ffmpeg not found (pip install imageio-ffmpeg)")
    enc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                            "-r", f"{args.fps:g}", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    reader = VideoReader(src, meta.get("fps"))
    rows, started, n = [], time.time(), 0
    try:
        while True:
            frame, t = reader.next(1.0 / args.fps)
            if frame is None:
                break
            worker.fps = n / (time.time() - started) if n else 0.0  # processing rate, shown on the video
            state, annotated = worker._process(frame, t, None, "VIDEO", f"{mmss(t)} / {mmss(meta['duration_s'])}")
            enc.stdin.write(annotated[:h, :w].tobytes())
            tr = state["tracking"]
            rows.append({"video_time_s": round(t, 2), "people_detected": state["people"], "people_with_id": tr["active_count"],
                         "unique_so_far": tr["unique"], "in": sum(ln["in"] for ln in tr["lines"]),
                         "out": sum(ln["out"] for ln in tr["lines"])})
            n += 1
            if n % 10 == 0:
                el = time.time() - started
                print(f"  {mmss(t)} / {mmss(meta['duration_s'])}: {state['people']} people in frame, {tr['unique']} unique so far "
                      f"({el / n:.1f} s per frame)", flush=True)
    finally:
        reader.close()
        enc.stdin.close()
        enc.wait()
    with open(out.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["video_time_s"])
        wr.writeheader()
        wr.writerows(rows)
    people = [r["people_detected"] for r in rows] or [0]
    print(f"\nDone: {n} frames analysed in {time.time() - started:.0f} s -> {out}")
    print(f"People detected per frame: average {sum(people) / len(people):.1f}, max {max(people)}; "
          f"unique tracking IDs (seen 1 s or more): {rows[-1]['unique_so_far'] if rows else 0}; "
          f"counting line IN {rows[-1]['in'] if rows else 0} / OUT {rows[-1]['out'] if rows else 0}")


if __name__ == "__main__":
    main()
