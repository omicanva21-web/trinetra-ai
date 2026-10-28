"""Floor calibration and polygon helpers: pixels in, metres out."""
from __future__ import annotations

import cv2
import numpy as np


class FloorCalibration:
    """Maps image pixels to floor metres from four clicked corners of a known rectangle.

    image_points: four [x, y] pixel points, clicked in this order on the floor:
        near-left, near-right, far-right, far-left
    width_m:  real distance near-left -> near-right (metres)
    length_m: real distance near-left -> far-left (metres)
    """

    def __init__(self, image_points, width_m: float, length_m: float):
        src = np.asarray(image_points, dtype=np.float32).reshape(4, 2)
        dst = np.array(
            [[0, 0], [width_m, 0], [width_m, length_m], [0, length_m]], dtype=np.float32
        )
        self.H = cv2.getPerspectiveTransform(src, dst)
        self.H_inv = np.linalg.inv(self.H)

    def to_floor(self, points_px) -> np.ndarray:
        pts = np.asarray(points_px, dtype=np.float32).reshape(-1, 2)
        if len(pts) == 0:
            return np.zeros((0, 2), dtype=np.float32)
        return cv2.perspectiveTransform(pts.reshape(-1, 1, 2), self.H).reshape(-1, 2)

    def to_image(self, points_m) -> np.ndarray:
        pts = np.asarray(points_m, dtype=np.float32).reshape(-1, 2)
        if len(pts) == 0:
            return np.zeros((0, 2), dtype=np.float32)
        return cv2.perspectiveTransform(pts.reshape(-1, 1, 2), self.H_inv).reshape(-1, 2)

    @classmethod
    def from_config(cls, cfg: dict | None) -> "FloorCalibration | None":
        if not cfg:
            return None
        return cls(cfg["image_points"], cfg["width_m"], cfg["length_m"])


def polygon_area(points) -> float:
    """Shoelace formula. Works in any units (pixels or metres)."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    x, y = p[:, 0], p[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def foot_point(box) -> tuple[float, float]:
    """Bottom-centre of a box: where the person touches the floor."""
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, float(y2))


def point_in_polygon(polygon_px: np.ndarray, point) -> bool:
    return cv2.pointPolygonTest(polygon_px, (float(point[0]), float(point[1])), False) >= 0
