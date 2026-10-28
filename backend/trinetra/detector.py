"""Person and vehicle detection with tracking IDs.

Three real detectors, chosen automatically (TRINETRA_DETECTOR=auto):
  1. "yolo":    Ultralytics YOLO26n + ByteTrack, used for every camera when Ultralytics is installed.
  2. "nanodet": NanoDet-Plus (COCO, Apache-2.0) on OpenCV DNN, cameras set to model "fast" (default):
                light enough for smooth live webcam tracking on a laptop CPU.
  3. "yolox":   YOLOX-S (COCO, Apache-2.0) on OpenCV DNN, cameras set to model "accurate":
                better for small, distant people; about 9x more compute.
  4. "crowd":   YOLOX-M on overlapping tiles plus one full-frame pass, cameras set to model "crowd" (Dense crowd):
                for high-angle footage of packed halls, where people are small and half hidden. Slow (about 20
                model runs per frame), meant for uploaded videos. Uses ONNX Runtime when installed (about 2x faster).
  2, 3 and 4 need only opencv-python and the model files, and use Trinetra's ByteTrack-style tracker.
Each camera gets its own detector instance, because tracker state belongs to one video stream.

A detection is {"id": int | None, "cls": "person" | "vehicle", "box": [x1, y1, x2, y2], "conf": float}.
"""
from __future__ import annotations

import hashlib
import logging
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from . import config
from .tracking import ByteTrackLite, CameraMotion

log = logging.getLogger("trinetra.detector")

# COCO class ids: 0 person, 1 bicycle, 2 car, 3 motorcycle, 5 bus, 7 truck
CLASS_MAP = {0: "person", 1: "vehicle", 2: "vehicle", 3: "vehicle", 5: "vehicle", 7: "vehicle"}

YOLOX_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "object_detection_yolox/object_detection_yolox_2022nov.onnx")
YOLOX_SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"


# ---------------------------------------------------------------- Ultralytics YOLO + ByteTrack
class YoloDetector:
    name = "YOLO26n + ByteTrack"

    def __init__(self, weights: str = config.YOLO_WEIGHTS, imgsz: int = config.YOLO_IMGSZ,
                 conf: float = 0.15, device: str | None = config.YOLO_DEVICE):
        from ultralytics import YOLO  # imported here so the app runs without PyTorch

        weights_path = config.MODELS_DIR / weights
        self.model = YOLO(str(weights_path) if weights_path.exists() else weights)
        self.imgsz, self.conf, self.device = imgsz, conf, device
        self.name = f"{Path(weights).stem} + ByteTrack"

    def detect(self, frame, t: float | None = None) -> list[dict]:
        # conf is low on purpose: ByteTrack uses weak boxes to keep half-hidden people tracked
        r = self.model.track(frame, persist=True, tracker="bytetrack.yaml", imgsz=self.imgsz,
                             conf=self.conf, classes=list(CLASS_MAP), device=self.device, verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []
        xyxy = r.boxes.xyxy.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy().astype(int)
        conf = r.boxes.conf.cpu().numpy()
        ids = r.boxes.id.cpu().numpy().astype(int).tolist() if r.boxes.id is not None else [None] * len(cls)
        return [{"id": tid, "cls": CLASS_MAP[c], "box": [float(v) for v in box], "conf": float(p)}
                for box, c, p, tid in zip(xyxy, cls, conf, ids) if tid is not None or p >= 0.45]

    def reset(self) -> None:
        """Forget all tracks (uploaded video restarted). The ID counter is shared, so IDs keep counting up."""
        predictor = getattr(self.model, "predictor", None)
        for tr in getattr(predictor, "trackers", None) or []:
            for attr in ("tracked_stracks", "lost_stracks", "removed_stracks"):
                if hasattr(tr, attr):
                    setattr(tr, attr, [])
            if hasattr(tr, "frame_id"):
                tr.frame_id = 0


# ---------------------------------------------------------------- YOLOX on OpenCV DNN
def ensure_yolox_model() -> Path:
    path = config.MODELS_DIR / "yolox_s.onnx"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading YOLOX model (36 MB) to %s", path)
    tmp = path.with_suffix(".part")
    urllib.request.urlretrieve(YOLOX_URL, tmp)
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if digest != YOLOX_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("downloaded YOLOX model failed its checksum")
    tmp.replace(path)
    return path


class YoloxDetector:
    name = "YOLOX-S (OpenCV) + ByteTrack-lite"
    SIZE = 640
    TRACKER_ARGS: dict = {}

    def __init__(self, conf: float = 0.15, nms: float = 0.45):
        self.net = cv2.dnn.readNet(str(ensure_yolox_model()))
        self.conf, self.nms = conf, nms
        grids, strides = [], []
        for s in (8, 16, 32):
            n = self.SIZE // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), s))
        self.grids, self.strides = np.concatenate(grids), np.concatenate(strides)
        self.tracker = ByteTrackLite(**self.TRACKER_ARGS)

    def raw_detect(self, frame) -> list[dict]:
        h, w = frame.shape[:2]
        ratio = min(self.SIZE / h, self.SIZE / w)
        padded = np.full((self.SIZE, self.SIZE, 3), 114.0, np.float32)
        resized = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (int(w * ratio), int(h * ratio)))
        padded[: resized.shape[0], : resized.shape[1]] = resized
        self.net.setInput(padded.transpose(2, 0, 1)[np.newaxis])
        out = self.net.forward(self.net.getUnconnectedOutLayersNames())[0][0].copy()
        out[:, :2] = (out[:, :2] + self.grids) * self.strides
        out[:, 2:4] = np.exp(out[:, 2:4]) * self.strides
        scores = out[:, 4:5] * out[:, 5:]
        cls = scores.argmax(1)
        best = scores[np.arange(len(scores)), cls]
        keep = np.isin(cls, list(CLASS_MAP)) & (best >= self.conf)
        if not keep.any():
            return []
        b, best, cls = out[keep, :4], best[keep], cls[keep]
        xywh = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 2], b[:, 3]], 1) / ratio
        idx = cv2.dnn.NMSBoxesBatched(xywh.tolist(), best.tolist(), cls.tolist(), self.conf, self.nms)
        dets = []
        for i in np.array(idx).reshape(-1):
            x, y, bw, bh = xywh[i]
            dets.append({"id": None, "cls": CLASS_MAP[int(cls[i])], "conf": float(best[i]),
                         "box": [max(0.0, float(x)), max(0.0, float(y)), min(w, float(x + bw)), min(h, float(y + bh))]})
        return dets

    def detect(self, frame, t: float | None = None) -> list[dict]:
        return self.tracker.update(self.raw_detect(frame), time.monotonic() if t is None else t)

    def reset(self) -> None:
        """Forget all tracks; IDs start again at 1 (uploaded video restarted)."""
        self.tracker = ByteTrackLite(**self.TRACKER_ARGS)


# ---------------------------------------------------------------- NanoDet-Plus on OpenCV DNN (fast)
NANODET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
               "object_detection_nanodet/object_detection_nanodet_2022nov.onnx")
NANODET_SHA256 = "4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186"


def ensure_model(name: str, url: str, sha256: str) -> Path:
    path = config.MODELS_DIR / name
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading %s to %s", name, path)
    tmp = path.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    if hashlib.sha256(tmp.read_bytes()).hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded {name} failed its checksum")
    tmp.replace(path)
    return path


class NanodetDetector:
    """NanoDet-Plus-m 416 (COCO, Apache-2.0): about 20x less compute than YOLOX-S, so live webcam
    tracking stays smooth on an ordinary laptop CPU. Less accurate for small, distant people.
    Pre/post-processing follows OpenCV Zoo's reference implementation."""

    name = "NanoDet-Plus (OpenCV, fast) + ByteTrack-lite"
    SIZE, STRIDES, REG_MAX = 416, (8, 16, 32, 64), 7
    # on real footage, cones/posts/rocks stay below ~0.5 here while people reach 0.65+
    TRACKER_ARGS = {"high": 0.45, "new_track": 0.45, "confirm_conf": 0.6}
    MEAN = np.array([103.53, 116.28, 123.675], np.float32)
    STD = np.array([57.375, 57.12, 58.395], np.float32)

    def __init__(self, conf: float = 0.15, nms: float = 0.5):
        self.net = cv2.dnn.readNet(str(ensure_model("nanodet_plus_m_416.onnx", NANODET_URL, NANODET_SHA256)))
        self.conf, self.nms = conf, nms
        self.anchors = []
        for s in self.STRIDES:
            n = self.SIZE // s
            xv, yv = np.meshgrid(np.arange(n) * s, np.arange(n) * s)
            self.anchors.append(np.column_stack((xv.flatten() + 0.5 * (s - 1), yv.flatten() + 0.5 * (s - 1))))
        self.project = np.arange(self.REG_MAX + 1, dtype=np.float32)
        self.tracker = ByteTrackLite(**self.TRACKER_ARGS)

    def raw_detect(self, frame) -> list[dict]:
        h, w = frame.shape[:2]
        scale = min(self.SIZE / h, self.SIZE / w)
        nw, nh = int(w * scale), int(h * scale)
        left, top = (self.SIZE - nw) // 2, (self.SIZE - nh) // 2
        img = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (nw, nh), interpolation=cv2.INTER_AREA)
        img = cv2.copyMakeBorder(img, top, self.SIZE - nh - top, left, self.SIZE - nw - left, cv2.BORDER_CONSTANT, value=0)
        self.net.setInput(cv2.dnn.blobFromImage((img.astype(np.float32) - self.MEAN) / self.STD))
        outs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        # pair class and box outputs by their number of anchor points (output order differs between
        # OpenCV versions): class scores have 80 columns, box distributions 4 x (REG_MAX + 1)
        levels: dict[int, dict] = {}
        for o in outs:
            o = o.reshape(-1, o.shape[-1])
            levels.setdefault(o.shape[0], {})["cls" if o.shape[1] == 80 else "box"] = o
        boxes, scores = [], []
        for stride, anchors in zip(self.STRIDES, self.anchors):
            lv = levels.get(len(anchors))
            if not lv or "cls" not in lv or "box" not in lv:
                continue
            cls_score, bbox_pred = lv["cls"], lv["box"]
            e = np.exp(bbox_pred.reshape(-1, self.REG_MAX + 1))
            dist = ((e / e.sum(1, keepdims=True)) @ self.project).reshape(-1, 4) * stride
            boxes.append(np.column_stack([anchors[:, 0] - dist[:, 0], anchors[:, 1] - dist[:, 1],
                                          anchors[:, 0] + dist[:, 2], anchors[:, 1] + dist[:, 3]]))
            scores.append(cls_score)
        boxes, scores = np.concatenate(boxes), np.concatenate(scores)
        cls = scores.argmax(1)
        best = scores[np.arange(len(scores)), cls]
        keep = np.isin(cls, list(CLASS_MAP)) & (best >= self.conf)
        if not keep.any():
            return []
        b, best, cls = boxes[keep], best[keep], cls[keep]
        b = (b - np.array([left, top, left, top])) / scale  # back to frame pixels
        b = np.clip(b, 0, [w, h, w, h])
        xywh = np.column_stack([b[:, :2], b[:, 2:] - b[:, :2]])
        idx = cv2.dnn.NMSBoxesBatched(xywh.tolist(), best.tolist(), cls.tolist(), self.conf, self.nms)
        return [{"id": None, "cls": CLASS_MAP[int(cls[i])], "conf": float(best[i]), "box": [float(v) for v in b[i]]}
                for i in np.array(idx).reshape(-1)]

    def detect(self, frame, t: float | None = None) -> list[dict]:
        return self.tracker.update(self.raw_detect(frame), time.monotonic() if t is None else t)

    def reset(self) -> None:
        """Forget all tracks; IDs start again at 1 (uploaded video restarted)."""
        self.tracker = ByteTrackLite(**self.TRACKER_ARGS)


# ---------------------------------------------------------------- dense crowds: YOLOX-M on tiles
class Interrupted(Exception):
    """A slow frame was abandoned because the operator pressed a button (Pause, Stop, ...)."""
YOLOX_M_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_m.onnx"
YOLOX_M_SHA256 = "21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f"


class OnnxRunner:
    """One ONNX model: ONNX Runtime when installed (about 2x faster on a CPU), otherwise OpenCV DNN."""

    def __init__(self, path: Path):
        self.sess = None
        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            self.sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
            self.input = self.sess.get_inputs()[0].name
            self.engine = "ONNX Runtime"
        except Exception:  # not installed or no wheel for this Python: OpenCV runs the same model
            self.net = cv2.dnn.readNet(str(path))
            self.engine = "OpenCV"

    def __call__(self, blob: np.ndarray) -> np.ndarray:
        if self.sess is not None:
            return self.sess.run(None, {self.input: blob})[0]
        self.net.setInput(blob)
        return self.net.forward(self.net.getUnconnectedOutLayersNames())[0]


def nms_dets(dets: list[dict], iou: float) -> list[dict]:
    if not dets:
        return []
    rects = [[d["box"][0], d["box"][1], d["box"][2] - d["box"][0], d["box"][3] - d["box"][1]] for d in dets]
    keep = cv2.dnn.NMSBoxes(rects, [d["conf"] for d in dets], 0.0, iou)
    return [dets[i] for i in np.array(keep).flatten()]


class CrowdDetector:
    """Packed rooms filmed from above (halls, stands, queues): people are small, seated and half hidden.

    The frame is cut into overlapping tiles (5 x 4 for an 854 x 480 video); each tile is enlarged to the model's 640 px,
    so a person 20 px tall becomes ~60 px, which YOLOX-M can recognise. One extra pass on the whole frame
    catches people too big for a tile. Duplicates are merged (overlap, and fragments lying mostly inside a
    stronger box). The tracker keeps still, seated people (no static-object filter) and accepts the weaker
    scores typical of crowds.
    """

    SIZE = 640
    # seated people: no static-object filter, longer gaps bridged, no distance "rescue" (it would hand an ID
    # to a neighbour in a packed room)
    # (tuned on a handheld 854x480 hall video: with camera-motion compensation the median ID lasted 12 s
    # instead of 6.5 s, and ~58 people per frame kept an ID)
    TRACKER_ARGS = {"high": 0.3, "low": 0.12, "new_track": 0.3, "confirm_conf": 0.4, "iou_high": 0.15,
                    "iou_low": 0.2, "max_lost_s": 6.0, "static_after_s": 1e9, "rescue": False, "predict_s": 0.0}

    def __init__(self, cols: int | None = None, rows: int | None = None, overlap: float = 0.25, conf: float = 0.2,
                 nms: float = 0.45):
        try:
            path, self.bgr, label = ensure_model("yolox_m.onnx", YOLOX_M_URL, YOLOX_M_SHA256), True, "YOLOX-M"
        except Exception as exc:  # offline and not downloaded yet: the bundled YOLOX-S (fewer people found)
            log.warning("YOLOX-M unavailable (%s); dense-crowd mode uses YOLOX-S", exc)
            path, self.bgr, label = ensure_yolox_model(), False, "YOLOX-S"
        self.run = OnnxRunner(path)
        self.cols, self.rows, self.overlap, self.conf, self.nms = cols, rows, overlap, conf, nms
        grids, strides = [], []
        for s in (8, 16, 32):
            n = self.SIZE // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), s))
        self.grids, self.strides = np.concatenate(grids), np.concatenate(strides)
        self.tracker = ByteTrackLite(**self.TRACKER_ARGS)
        self.motion = CameraMotion()  # handheld phone videos: follow the camera's own movement
        self.should_stop = None  # set by the worker: a frame takes seconds, buttons must not wait for it
        self.name = f"{label} dense crowd (tiled, {self.run.engine}) + ByteTrack-lite"

    def _infer(self, img) -> list[dict]:
        h, w = img.shape[:2]
        ratio = min(self.SIZE / h, self.SIZE / w)
        padded = np.full((self.SIZE, self.SIZE, 3), 114.0, np.float32)
        src = img if self.bgr else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)  # Megvii models: BGR; OpenCV Zoo's: RGB
        resized = cv2.resize(src, (max(1, int(w * ratio)), max(1, int(h * ratio))), interpolation=cv2.INTER_LINEAR)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        out = self.run(padded.transpose(2, 0, 1)[np.newaxis].copy())[0].copy()
        out[:, :2] = (out[:, :2] + self.grids) * self.strides
        out[:, 2:4] = np.exp(out[:, 2:4]) * self.strides
        scores = out[:, 4:5] * out[:, 5:]
        cls = scores.argmax(1)
        best = scores[np.arange(len(scores)), cls]
        keep = np.isin(cls, list(CLASS_MAP)) & (best >= self.conf)
        dets = []
        for (cx, cy, bw, bh), c, p in zip(out[keep, :4], cls[keep], best[keep]):
            dets.append({"id": None, "cls": CLASS_MAP[int(c)], "conf": float(p),
                         "box": [float((cx - bw / 2) / ratio), float((cy - bh / 2) / ratio),
                                 float((cx + bw / 2) / ratio), float((cy + bh / 2) / ratio)]})
        return nms_dets(dets, self.nms)

    def grid(self, w: int, h: int) -> tuple[int, int]:
        """Tiles of about 170 x 120 source pixels (5 x 4 for 854 x 480), at most 6 x 4; small frames get fewer."""
        return (self.cols or max(1, min(6, int(w / 170))), self.rows or max(1, min(4, int(h / 120))))

    def raw_detect(self, frame) -> list[dict]:
        h, w = frame.shape[:2]
        cols, rows = self.grid(w, h)
        tw = int(w / (cols - (cols - 1) * self.overlap))
        th = int(h / (rows - (rows - 1) * self.overlap))
        found = self._infer(frame)  # whole frame: near, large people
        for r in range(rows if cols * rows > 1 else 0):
            for c in range(cols):
                x0 = min(w - tw, int(c * tw * (1 - self.overlap)))
                y0 = min(h - th, int(r * th * (1 - self.overlap)))
                if self.should_stop is not None and self.should_stop():
                    raise Interrupted()
                for d in self._infer(frame[y0:y0 + th, x0:x0 + tw]):
                    x1, y1, x2, y2 = d["box"]
                    found.append({**d, "box": [x1 + x0, y1 + y0, x2 + x0, y2 + y0]})
        found = nms_dets(found, 0.5)
        # a person cut by a tile edge leaves a fragment inside their full box: keep the stronger, larger one
        found.sort(key=lambda d: -d["conf"])
        keep = []
        for d in found:
            x1, y1, x2, y2 = d["box"]
            area = max(1.0, (x2 - x1) * (y2 - y1))
            inside = any(max(0.0, min(x2, k["box"][2]) - max(x1, k["box"][0])) *
                         max(0.0, min(y2, k["box"][3]) - max(y1, k["box"][1])) > 0.7 * area for k in keep)
            if not inside:
                keep.append(d)
        return keep

    def detect(self, frame, t: float | None = None) -> list[dict]:
        dets = self.raw_detect(frame)  # may raise Interrupted: then nothing below has changed
        m = self.motion.estimate(frame)
        if m is not None:
            self.tracker.compensate(m)
        return self.tracker.update(dets, time.monotonic() if t is None else t)

    def reset(self) -> None:
        self.tracker = ByteTrackLite(**self.TRACKER_ARGS)
        self.motion.reset()


# ---------------------------------------------------------------- choose
def make_detector(kind: str = config.DETECTOR, model: str = "fast"):
    """Returns (detector or None, error text).

    kind:  auto | yolo | yolox | nanodet | off   (global setting, TRINETRA_DETECTOR)
    model: fast | accurate | crowd               (per camera; with kind=auto and no Ultralytics YOLO,
                                                  fast = NanoDet-Plus, accurate = YOLOX-S;
                                                  crowd = tiled YOLOX-M for every kind except off)
    """
    if kind == "off":
        return None, "detector off (video only)"
    if model == "crowd":
        try:
            return CrowdDetector(), None
        except Exception as exc:
            return None, f"dense-crowd detector unavailable ({exc.__class__.__name__}: {exc})"
    errors = []
    if kind in ("auto", "yolo"):
        try:
            return YoloDetector(), None
        except Exception as exc:  # most often: ultralytics / torch not installed
            errors.append(f"YOLO unavailable ({exc.__class__.__name__}: {exc})")
            if kind == "yolo":
                return None, "; ".join(errors)
    order = ["nanodet", "yolox"] if (kind == "nanodet" or (kind == "auto" and model == "fast")) else ["yolox", "nanodet"]
    if kind in ("yolox", "nanodet"):
        order = order[:1]
    for name in order:
        try:
            return (NanodetDetector() if name == "nanodet" else YoloxDetector()), None
        except Exception as exc:
            errors.append(f"{name} unavailable ({exc.__class__.__name__}: {exc})")
    return None, "; ".join(errors) or f"unknown detector {kind!r}"
