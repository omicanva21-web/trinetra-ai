"""Synthetic camera: a crowd that fills a zone plus a periodic intruder.

Lets the frontend and backend be built and tested without a GPU, YOLO or real footage.
It is a SIMULATION: label it as such if it is ever shown to judges.
"""
from __future__ import annotations

import cv2
import numpy as np

from .analytics.geometry import FloorCalibration, point_in_polygon


class MockScene:
    W, H = 960, 540

    def __init__(self, camera_cfg: dict, seed: int = 7, cycle_s: float = 220.0):
        cal = camera_cfg.get("calibration") or {"image_points": [[120, 520], [840, 520], [620, 150], [340, 150]],
                                                "width_m": 10.0, "length_m": 14.0}
        self.calib = FloorCalibration.from_config(cal)
        self.fw, self.fl = cal["width_m"], cal["length_m"]
        zones = {z["kind"]: z for z in camera_cfg.get("zones", [])}
        if "crowd" in zones:
            self.crowd_floor = self.calib.to_floor(np.asarray(zones["crowd"]["polygon"], np.float32)).reshape(-1, 1, 2)
        else:  # no crowd zone drawn: people gather in the middle of the floor
            self.crowd_floor = np.array([[2, 4], [8, 4], [8, 9], [2, 9]], np.float32).reshape(-1, 1, 2)
        self.restricted_px = np.asarray(zones["restricted"]["polygon"], np.float32) if "restricted" in zones else None
        self.rng = np.random.default_rng(seed)
        self.cycle_s = cycle_s
        self.people: list[dict] = []
        self.next_id = 1
        self.last_t = None
        self.spawn_acc = 0.0
        self.background = self._draw_background()

    def _draw_background(self):
        img = np.full((self.H, self.W, 3), 38, np.uint8)
        floor = self.calib.to_image([[0, 0], [self.fw, 0], [self.fw, self.fl], [0, self.fl]]).astype(np.int32)
        cv2.fillPoly(img, [floor], (70, 70, 70))
        for x in range(int(self.fw) + 1):
            a, b = self.calib.to_image([[x, 0], [x, self.fl]]).astype(int)
            cv2.line(img, tuple(a), tuple(b), (85, 85, 85), 1)
        for y in range(int(self.fl) + 1):
            a, b = self.calib.to_image([[0, y], [self.fw, y]]).astype(int)
            cv2.line(img, tuple(a), tuple(b), (85, 85, 85), 1)
        cv2.putText(img, "SIMULATED FEED", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
        return img

    def _random_target(self):
        xs, ys = self.crowd_floor[:, 0, 0], self.crowd_floor[:, 0, 1]
        for _ in range(50):
            p = (self.rng.uniform(xs.min(), xs.max()), self.rng.uniform(ys.min(), ys.max()))
            if point_in_polygon(self.crowd_floor, p):
                return np.array(p)
        return np.array([xs.mean(), ys.mean()])

    def step(self, t: float):
        dt = 0.0 if self.last_t is None else min(0.5, t - self.last_t)
        self.last_t = t
        phase = t % self.cycle_s
        rate = 0.8 if phase < 100 else 0.05  # people per second arriving
        self.spawn_acc += rate * dt
        while self.spawn_acc >= 1:
            self.spawn_acc -= 1
            self.people.append({"id": self.next_id, "pos": np.array([self.rng.uniform(1, self.fw - 1), 0.2]),
                                "target": self._random_target(), "state": "in", "wait": self.rng.uniform(70, 150)})
            self.next_id += 1

        inside = [p for p in self.people if point_in_polygon(self.crowd_floor, p["pos"])]
        crowd_factor = max(0.15, 1 - len(inside) / 60)
        for p in self.people:
            if p["state"] == "in":
                d = p["target"] - p["pos"]
                dist = float(np.linalg.norm(d))
                if dist < 0.2:
                    p["state"] = "wait"
                else:
                    p["pos"] = p["pos"] + d / dist * min(dist, 1.2 * crowd_factor * dt)
            elif p["state"] == "wait":
                p["wait"] -= dt
                p["pos"] = p["pos"] + self.rng.normal(0, 0.05, 2) * dt
                if p["wait"] <= 0:
                    p["state"], p["target"] = "out", np.array([p["pos"][0], self.fl + 0.5])
            else:
                p["pos"][1] += 1.0 * crowd_factor * dt
        self.people = [p for p in self.people if p["pos"][1] < self.fl - 0.2]

        frame = self.background.copy()
        dets = []
        feet = self.calib.to_image([p["pos"] for p in self.people]) if self.people else []
        order = np.argsort([-f[1] for f in feet]) if len(feet) else []
        for i in reversed(order):  # far people first so near ones are drawn on top
            dets.append(self._person(frame, self.people[i]["id"], feet[i]))

        if self.restricted_px is not None:  # one intruder every 50 s, lingers ~10 s
            k = t % 50
            if 20 <= k <= 38:
                cx, cy = self.restricted_px[:, 0].mean(), self.restricted_px[:, 1].mean()
                start = np.array([self.W - 5.0, cy + 30])
                pos = start + (np.array([cx, cy]) - start) * min(1.0, (k - 20) / 4) if k < 34 else \
                    np.array([cx, cy]) + (start - np.array([cx, cy])) * min(1.0, (k - 34) / 4)
                dets.append(self._person(frame, 9000 + int(t // 50), pos, colour=(60, 60, 220)))

        dets = [d for d in dets if self.rng.random() > 0.03]  # a detector misses some boxes
        return frame, dets

    def _person(self, frame, pid, foot, colour=None):
        x, y = float(foot[0]), float(foot[1])
        h = 25 + 0.22 * max(0.0, y - 150)
        w = 0.4 * h
        colour = colour or tuple(int(c) for c in (120 + (pid * 37) % 120, 120 + (pid * 53) % 120, 140))
        cv2.rectangle(frame, (int(x - w / 2), int(y - h * 0.8)), (int(x + w / 2), int(y)), colour, -1)
        cv2.circle(frame, (int(x), int(y - h * 0.88)), max(2, int(h * 0.12)), (180, 190, 210), -1)
        j = self.rng.normal(0, 1.5, 4)
        return {"id": pid, "cls": "person", "conf": 0.8,
                "box": [x - w / 2 + j[0], y - h + j[1], x + w / 2 + j[2], y + j[3]]}

