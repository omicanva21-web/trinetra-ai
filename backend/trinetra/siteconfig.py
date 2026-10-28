"""site.json and profiles.json: validation, safe saving, and normalised (0-1) coordinates.

Zones, counting lines and calibration points are stored as fractions of the frame (polygon_norm,
points_norm, image_points_norm), so a zone drawn once keeps working at any camera resolution.
Older pixel fields (polygon, image_points) are still accepted.
"""
from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import config

_lock = threading.Lock()

Point = tuple[float, float]


def _check_norm(pts):
    for x, y in pts:
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("points must be fractions of the frame (0 to 1)")
    return [(round(x, 4), round(y, 4)) for x, y in pts]


class ZoneIn(BaseModel):
    id: str | None = Field(default=None, max_length=20)
    name: str = Field(min_length=1, max_length=40)
    kind: Literal["crowd", "restricted"]
    polygon_norm: list[Point] = Field(min_length=3, max_length=24)
    area_m2: float | None = Field(default=None, gt=0, le=100000)
    base_score: float | None = Field(default=None, ge=0, le=100)
    dwell_limit_s: float | None = Field(default=None, ge=1, le=3600)
    classes: list[Literal["person", "vehicle"]] | None = None

    @field_validator("polygon_norm")
    @classmethod
    def inside_frame(cls, v):
        return _check_norm(v)


class LineIn(BaseModel):
    id: str | None = Field(default=None, max_length=20)
    name: str = Field(min_length=1, max_length=40)
    points_norm: list[Point] = Field(min_length=2, max_length=2)

    @field_validator("points_norm")
    @classmethod
    def inside_frame(cls, v):
        return _check_norm(v)

    @model_validator(mode="after")
    def not_a_dot(self):
        (x1, y1), (x2, y2) = self.points_norm
        if abs(x1 - x2) + abs(y1 - y2) < 0.02:
            raise ValueError("a counting line needs two points further apart")
        return self


class CalibrationIn(BaseModel):
    image_points_norm: list[Point] = Field(min_length=4, max_length=4)
    width_m: float = Field(gt=0, le=1000)
    length_m: float = Field(gt=0, le=1000)


class OptionsIn(BaseModel):
    max_fps: float = Field(default=10, ge=1, le=30)
    model: Literal["fast", "accurate", "crowd"] = "fast"
    heatmap: bool = True
    trails: bool = True


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    source: str = Field(min_length=1, max_length=500)
    enabled: bool = True
    zones: list[ZoneIn] = Field(default_factory=list, max_length=12)
    lines: list[LineIn] = Field(default_factory=list, max_length=8)
    calibration: CalibrationIn | None = None
    options: OptionsIn = Field(default_factory=OptionsIn)

    @model_validator(mode="after")
    def unique_ids(self):
        for items, prefix in ((self.zones, "z"), (self.lines, "l")):
            used = set()
            for i, it in enumerate(items):
                if not it.id or it.id in used:
                    n = i + 1
                    while f"{prefix}{n}" in used:
                        n += 1
                    it.id = f"{prefix}{n}"
                used.add(it.id)
        return self


class ProfileIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    density_warn: float = Field(gt=0, le=20)
    density_danger: float = Field(gt=0, le=20)
    eta_alert_s: float = Field(ge=10, le=1800)
    speed_surge_mps: float = Field(gt=0, le=10)
    dwell_limit_s: float = Field(ge=1, le=3600)
    pressure_ref: float = Field(gt=0, le=10)

    @model_validator(mode="after")
    def warn_below_danger(self):
        if self.density_warn >= self.density_danger:
            raise ValueError("density_warn must be lower than density_danger")
        return self


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic on Windows and POSIX: a crash never leaves half a file


def _repair(obj):
    """Fix names garbled by earlier versions on Windows ("Camera 4 â€” …" -> "Camera 4 — …")."""
    if isinstance(obj, str):
        return config.fix_mojibake(obj)
    if isinstance(obj, list):
        return [_repair(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _repair(v) for k, v in obj.items()}
    return obj


def _load_json(path: Path) -> dict:
    data = json.loads(config.read_text(path))
    fixed = _repair(data)
    if fixed != data:  # write the repaired text back once, as UTF-8
        _write_json(path, fixed)
    return fixed


def load_site() -> dict:
    with _lock:
        default = config.SITE_FILE.with_name("site.default.json")
        if not config.SITE_FILE.exists() and default.exists():  # fresh copy (e.g. from GitHub): start from the defaults
            _write_json(config.SITE_FILE, json.loads(config.read_text(default)))
        return _load_json(config.SITE_FILE)


def save_site(site: dict) -> None:
    with _lock:
        _write_json(config.SITE_FILE, site)


def load_profiles() -> dict:
    with _lock:
        return _load_json(config.PROFILES_FILE)


def save_profiles(profiles: dict) -> None:
    with _lock:
        _write_json(config.PROFILES_FILE, profiles)


def new_camera_id(site: dict) -> str:
    used = {c["id"] for c in site["cameras"]}
    n = 1
    while f"cam{n}" in used:
        n += 1
    return f"cam{n}"


def camera_to_store(cam_id: str, body: CameraIn) -> dict:
    body = CameraIn.model_validate(_repair(body.model_dump()))  # a page opened before the fix may send garbled names
    cam = {"id": cam_id, "name": body.name, "source": body.source.strip(), "enabled": body.enabled,
           "zones": [z.model_dump(exclude_none=True) for z in body.zones],
           "lines": [ln.model_dump() for ln in body.lines], "options": body.options.model_dump()}
    for z in cam["zones"]:
        z["polygon_norm"] = [list(p) for p in z["polygon_norm"]]
    for ln in cam["lines"]:
        ln["points_norm"] = [list(p) for p in ln["points_norm"]]
    if body.calibration:
        cam["calibration"] = {"image_points_norm": [list(p) for p in body.calibration.image_points_norm],
                              "width_m": body.calibration.width_m, "length_m": body.calibration.length_m}
    return cam


def options_of(camera_cfg: dict) -> dict:
    return {**OptionsIn().model_dump(), **(camera_cfg.get("options") or {})}


def resolve(camera_cfg: dict, width: int, height: int) -> dict:
    """Copy of the camera config with pixel coordinates for this frame size."""
    cfg = copy.deepcopy(camera_cfg)
    cal = cfg.get("calibration")
    if cal and "image_points_norm" in cal:
        cal["image_points"] = [[x * width, y * height] for x, y in cal["image_points_norm"]]
    for z in cfg.get("zones", []):
        if "polygon_norm" in z:
            z["polygon"] = [[x * width, y * height] for x, y in z["polygon_norm"]]
    for ln in cfg.get("lines", []):
        ln["points"] = [[x * width, y * height] for x, y in ln["points_norm"]]
    return cfg


def normalised_view(camera_cfg: dict, width: int | None, height: int | None) -> dict:
    """Copy for the Setup page: always has polygon_norm when the frame size is known."""
    cfg = copy.deepcopy(camera_cfg)
    for z in cfg.get("zones", []):
        if "polygon_norm" not in z and "polygon" in z and width and height:
            z["polygon_norm"] = [[round(x / width, 4), round(y / height, 4)] for x, y in z["polygon"]]
        z.pop("polygon", None)
    cal = cfg.get("calibration")
    if cal and "image_points_norm" not in cal and "image_points" in cal and width and height:
        cal["image_points_norm"] = [[round(x / width, 4), round(y / height, 4)] for x, y in cal["image_points"]]
    if cal:
        cal.pop("image_points", None)
    cfg.setdefault("lines", [])
    cfg["options"] = options_of(camera_cfg)
    return cfg


SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,20}$")

# Camera 4: videos uploaded from the dashboard. No restricted zone and no floor size by default, so a random
# recording never raises alerts by itself; draw zones on its frame in Setup once a video is loaded.
UPLOAD_CAMERA = {
    "name": "Camera 4 — Uploaded Video Tracking", "source": "upload", "enabled": True,
    "options": {"max_fps": 15, "model": "fast", "heatmap": False, "trails": True},
    "zones": [{"id": "z1", "name": "Whole view", "kind": "crowd",
               "polygon_norm": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]}],
    "lines": [{"id": "l1", "name": "Counting line", "points_norm": [[0.5, 1.0], [0.5, 0.0]]}],
}


def ensure_upload_camera(site: dict) -> bool:
    """Add Camera 4 once to configurations made before it existed. Returns True if site changed."""
    if site.get("upload_camera_added"):
        return False
    site["upload_camera_added"] = True
    if not any(str(c.get("source")) == "upload" for c in site["cameras"]):
        used = {c["id"] for c in site["cameras"]}
        cam_id = "cam4" if "cam4" not in used else new_camera_id(site)
        site["cameras"].append({"id": cam_id, **copy.deepcopy(UPLOAD_CAMERA)})
    return True
