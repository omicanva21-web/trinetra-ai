"""Multi-object tracker used with the YOLOX detector (ByteTrack-style, no appearance model).

How it works, per frame:
  1. Predict where every track should be now (constant velocity, in pixels per second).
  2. Match confident detections to tracks by box overlap (IoU); rescue fast movers by centre distance.
  3. Match the remaining confirmed tracks to low-confidence detections (a half-hidden person is
     often detected weakly; ByteTrack's key idea is to use those boxes instead of dropping the track).
  4. Unmatched confident detections start tentative tracks; a track gets its ID only after
     `min_hits` matches AND at least one strong detection (`confirm_conf`), so one-frame false
     detections and weak look-alikes (a cone, a post, a bin) never get an ID.
  5. Confirmed tracks that are not matched stay alive for `max_lost_s` seconds, so a person who is
     hidden briefly keeps the same ID when they reappear.
  6. A confirmed track that has not moved for `static_after_s` seconds and whose average score is
     weak is a static look-alike (a post, a bin, a rock), not a person: it loses its ID and is
     reported once as `demoted` so the analytics can forget it. People standing still score high.
"""
from __future__ import annotations

import cv2
import numpy as np


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between every box in a (N,4) and b (M,4), boxes as x1, y1, x2, y2."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


class _Track:
    __slots__ = ("id", "cls", "box", "pred", "v", "last_t", "hits", "confirmed", "conf", "best",
                 "born", "conf_sum", "c0", "max_disp", "static")

    def __init__(self, cls: str, box, t: float, conf: float):
        self.id = None  # assigned on confirmation
        self.cls, self.box, self.pred = cls, np.asarray(box, float), np.asarray(box, float)
        self.v = np.zeros(2)  # centre velocity, pixels per second
        self.last_t, self.hits, self.confirmed, self.conf, self.best = t, 1, False, conf, conf
        self.born, self.conf_sum, self.max_disp, self.static = t, conf, 0.0, False
        self.c0 = (self.box[:2] + self.box[2:]) / 2


class ByteTrackLite:
    def __init__(self, high: float = 0.45, low: float = 0.15, new_track: float = 0.5, iou_high: float = 0.2,
                 iou_low: float = 0.3, max_lost_s: float = 1.5, min_hits: int = 2, confirm_conf: float = 0.5,
                 static_after_s: float = 4.0, static_conf: float = 0.55, rescue: bool = True,
                 predict_s: float = 1.0):
        self.high, self.low, self.new_track = high, low, new_track
        self.rescue = rescue  # centre-distance matching for fast movers; off for packed crowds (wrong neighbour)
        self.predict_s = predict_s  # how far ahead motion is extrapolated; 0 for seated crowds (jitter, not motion)
        self.iou_high, self.iou_low = iou_high, iou_low
        self.max_lost_s, self.min_hits, self.confirm_conf = max_lost_s, min_hits, confirm_conf
        self.static_after_s, self.static_conf = static_after_s, static_conf
        self.tracks: list[_Track] = []
        self.next_id = 1

    @staticmethod
    def _greedy(scores: np.ndarray, thresh: float, higher_is_better: bool = True):
        pairs = []
        if scores.size:
            order = np.argsort(-scores if higher_is_better else scores, axis=None)
            used_r, used_c = set(), set()
            for flat in order:
                r, c = np.unravel_index(flat, scores.shape)
                s = scores[r, c]
                if (higher_is_better and s < thresh) or (not higher_is_better and s > thresh):
                    break
                if r in used_r or c in used_c:
                    continue
                used_r.add(r)
                used_c.add(c)
                pairs.append((int(r), int(c)))
        return pairs

    def _associate(self, tracks: list[_Track], dets: list[dict], iou_thresh: float, rescue: bool, t: float = 0.0):
        if not tracks or not dets:
            return [], list(range(len(tracks))), list(range(len(dets)))
        tb = np.array([t.pred for t in tracks])
        db = np.array([d["box"] for d in dets], float)
        same_cls = np.array([[t.cls == d["cls"] for d in dets] for t in tracks])
        iou = iou_matrix(tb, db) * same_cls
        pairs = self._greedy(iou, iou_thresh)
        mt, md = {r for r, _ in pairs}, {c for _, c in pairs}
        if rescue:  # fast movers at low fps overlap little: match by centre distance, similar size
            ut, ud = [i for i in range(len(tracks)) if i not in mt], [j for j in range(len(dets)) if j not in md]
            if ut and ud:
                tc = (tb[ut, :2] + tb[ut, 2:]) / 2
                dc = (db[ud, :2] + db[ud, 2:]) / 2
                tsize = np.maximum(tb[ut, 2] - tb[ut, 0], tb[ut, 3] - tb[ut, 1])
                dsize = np.maximum(db[ud, 2] - db[ud, 0], db[ud, 3] - db[ud, 1])
                gap = np.array([min(max(t - tracks[i].last_t, 0.0), self.max_lost_s) for i in ut])
                reach = np.maximum(tsize, 1) * (1.0 + gap)  # the longer someone was hidden, the further they may be
                dist = np.linalg.norm(tc[:, None] - dc[None], axis=2) / reach[:, None]
                ratio = dsize[None, :] / np.maximum(tsize[:, None], 1)
                ok = (ratio > 0.5) & (ratio < 2.0) & same_cls[np.ix_(ut, ud)]
                dist = np.where(ok, dist, np.inf)
                for r, c in self._greedy(dist, 0.6, higher_is_better=False):
                    pairs.append((ut[r], ud[c]))
                    mt.add(ut[r])
                    md.add(ud[c])
        return pairs, [i for i in range(len(tracks)) if i not in mt], [j for j in range(len(dets)) if j not in md]

    def _apply(self, tr: _Track, det: dict, t: float) -> dict:
        box = np.asarray(det["box"], float)
        dt = max(t - tr.last_t, 1e-3)
        old_c, new_c = (tr.box[:2] + tr.box[2:]) / 2, (box[:2] + box[2:]) / 2
        tr.v = 0.5 * tr.v + 0.5 * (new_c - old_c) / dt
        if iou_matrix(tr.pred[None], box[None])[0, 0] > 0.5:  # steady: smooth out detector jitter
            box = 0.7 * box + 0.3 * tr.pred
        tr.box, tr.last_t, tr.hits, tr.conf = box, t, tr.hits + 1, det["conf"]
        tr.best = max(tr.best, det["conf"])
        tr.conf_sum += det["conf"]
        tr.max_disp = max(tr.max_disp, float(np.linalg.norm(new_c - tr.c0)))
        if not tr.confirmed and not tr.static and tr.hits >= self.min_hits and tr.best >= self.confirm_conf:
            tr.confirmed, tr.id = True, self.next_id
            self.next_id += 1
        out = {**det, "box": [float(v) for v in box], "id": tr.id}
        if (tr.confirmed and t - tr.born >= self.static_after_s and tr.conf_sum / tr.hits < self.static_conf
                and tr.max_disp < 0.5 * (box[3] - box[1])):
            tr.static, tr.confirmed = True, False
            out.update(id=None, demoted=tr.id)
            tr.id = None
        return out

    def compensate(self, m: np.ndarray) -> None:
        """Move every track by the camera's own motion (2x3 affine, previous frame -> this frame)."""
        lin, off = m[:, :2], m[:, 2]
        for tr in self.tracks:
            corners = np.array([tr.box[:2], tr.box[2:]]) @ lin.T + off
            tr.box = np.concatenate([corners.min(0), corners.max(0)])
            tr.c0 = tr.c0 @ lin.T + off

    def update(self, dets: list[dict], t: float) -> list[dict]:
        for tr in self.tracks:
            shift = tr.v * min(t - tr.last_t, self.predict_s)
            tr.pred = tr.box + np.concatenate([shift, shift])
        high = [d for d in dets if d["conf"] >= self.high]
        low = [d for d in dets if self.low <= d["conf"] < self.high]
        out = []
        pairs, ut, ud = self._associate(self.tracks, high, self.iou_high, rescue=self.rescue, t=t)
        for ti, di in pairs:
            out.append(self._apply(self.tracks[ti], high[di], t))
        rest = [self.tracks[i] for i in ut if self.tracks[i].confirmed]
        pairs2, _, _ = self._associate(rest, low, self.iou_low, rescue=False)
        matched = {id(self.tracks[ti]) for ti, _ in pairs} | {id(rest[ti]) for ti, _ in pairs2}
        for ti, di in pairs2:
            out.append(self._apply(rest[ti], low[di], t))
        keep = []
        for tr in self.tracks:
            if id(tr) in matched:
                keep.append(tr)
            elif tr.confirmed and t - tr.last_t <= self.max_lost_s:
                keep.append(tr)  # lost for now; may come back with the same ID
        for di in ud:
            d = high[di]
            if d["conf"] >= self.new_track:
                keep.append(_Track(d["cls"], d["box"], t, d["conf"]))
                out.append({**d, "id": None})
        self.tracks = keep
        return out


class CameraMotion:
    """Global motion between consecutive analysed frames of a handheld video (phone recordings pan and shake).

    Corner features of the previous frame are followed with optical flow; a similarity transform fitted with
    RANSAC keeps the background (tables, walls) and ignores people who move. Returns None for a still camera.
    """

    def __init__(self, width: int = 480):
        self.width, self.prev = width, None

    def reset(self) -> None:
        self.prev = None

    def estimate(self, frame) -> np.ndarray | None:
        h, w = frame.shape[:2]
        s = min(1.0, self.width / w)
        small = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
        prev, self.prev = self.prev, gray
        if prev is None or prev.shape != gray.shape:
            return None
        p0 = cv2.goodFeaturesToTrack(prev, 400, 0.01, 8)
        if p0 is None or len(p0) < 20:
            return None
        p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, gray, p0, None)
        ok = st.reshape(-1) == 1
        if ok.sum() < 20:
            return None
        m, inliers = cv2.estimateAffinePartial2D(p0[ok], p1[ok], method=cv2.RANSAC, ransacReprojThreshold=2.0)
        if m is None or inliers is None or int(inliers.sum()) < 15:
            return None
        m = m.astype(float)
        m[:, 2] /= s
        if np.hypot(*m[:, 2]) < 0.75 and abs(np.hypot(m[0, 0], m[1, 0]) - 1.0) < 2e-3:
            return None  # the camera is still
        return m
