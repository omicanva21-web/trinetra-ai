"""Analyzer: detections for one frame in, zone state and incident events out.

This is the contract between the detector (YOLO or the mock scene) and everything else.
A detection is a dict: {"id": int | None, "cls": "person" | "vehicle", "box": [x1, y1, x2, y2], "conf": float}
"""
from __future__ import annotations

import threading

from .geometry import FloorCalibration, foot_point
from .risk import IncidentTracker, assess_crowd, assess_restricted, level_for
from .zones import TrackMotion, ZoneMonitor


class Analyzer:
    def __init__(self, camera_cfg: dict, profile: dict):
        self.camera_id = camera_cfg["id"]
        self.camera_name = camera_cfg.get("name", self.camera_id)
        self.calib = FloorCalibration.from_config(camera_cfg.get("calibration"))
        self.zones = [ZoneMonitor(z, self.calib) for z in camera_cfg.get("zones", [])]
        self.motion = TrackMotion()
        self.tracker = IncidentTracker(self.camera_id)
        self.profile = profile
        self.lock = threading.Lock()

    def set_profile(self, profile: dict) -> None:
        with self.lock:
            self.profile = profile

    def operator_closed(self, incident_id: str) -> None:
        with self.lock:
            self.tracker.operator_closed.add(incident_id)

    def finish(self, t: float) -> list[dict]:
        """Close every live incident: used when an uploaded video ends, stops or restarts."""
        with self.lock:
            events = self.tracker.close_all(t)
        for e in events:
            e["type"] = "incident"
        return events

    def analyze(self, detections: list[dict], t: float) -> tuple[dict, list[dict]]:
        with self.lock:
            p = self.profile
            for d in detections:
                d["foot"] = foot_point(d["box"])
            velocities = {}
            if self.calib is not None:
                tracked = [d for d in detections if d.get("id") is not None]
                floor = self.calib.to_floor([d["foot"] for d in tracked])
                velocities = self.motion.update(t, {d["id"]: tuple(xy) for d, xy in zip(tracked, floor)})

            zones_out, events = [], []
            for z in self.zones:
                inside = [d for d in detections if d["cls"] in z.classes and z.contains(d["foot"])]
                m = z.update(t, inside, velocities, p)
                if z.kind == "crowd":
                    score, reasons = assess_crowd(m, p)
                    kind = "crowd_density" if not any(r["signal"] == "surge" and r["points"] >= 10 for r in reasons) else "crowd_surge"
                else:
                    score, reasons = assess_restricted(m, p, z.cfg)
                    kind = "intrusion" if m["max_dwell_s"] < z.cfg.get("dwell_limit_s", p["dwell_limit_s"]) else "loitering"
                events += self.tracker.step(t, z.id, z.name, kind, score, reasons, m)
                zones_out.append({"id": z.id, "name": z.name, "kind": z.kind, "score": round(score),
                                  "level": level_for(score), "reasons": reasons, **m})

            top = max(zones_out, key=lambda z: z["score"], default=None)
            state = {
                "type": "state",
                "camera_id": self.camera_id,
                "camera_name": self.camera_name,
                "t": round(t, 2),
                "people": sum(1 for d in detections if d["cls"] == "person"),
                "vehicles": sum(1 for d in detections if d["cls"] == "vehicle"),
                "score": top["score"] if top else 0,
                "level": top["level"] if top else "LOW",
                "zones": zones_out,
            }
            for e in events:
                e["type"] = "incident"
            return state, events
