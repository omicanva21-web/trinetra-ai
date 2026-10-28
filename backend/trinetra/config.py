"""Settings from .env and environment variables."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_text(path: Path) -> str:
    """Trinetra's text files are UTF-8. Without saying so, Python on Windows reads them as Windows-1252, which turned
    "Camera 4 — Uploaded" into "Camera 4 â€” Uploaded". Files that older versions wrote in Windows-1252 still load."""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig")  # -sig: also accepts the byte-order mark Notepad may add
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


_MOJIBAKE = ("â€", "Ã", "Â")


def fix_mojibake(text: str) -> str:
    """Repair text that was UTF-8 read as Windows-1252 ("â€”" -> "—"); anything else is returned unchanged."""
    if not isinstance(text, str) or not any(m in text for m in _MOJIBAKE):
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _load_env(path: Path) -> None:
    """Tiny .env reader (KEY=VALUE lines) so python-dotenv is not needed."""
    if not path.exists():
        return
    for line in read_text(path).splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.split(" #", 1)[0].strip())  # allow inline comments


_load_env(ROOT / ".env")

SITE_FILE = Path(os.getenv("TRINETRA_SITE", ROOT / "config" / "site.json"))
PROFILES_FILE = Path(os.getenv("TRINETRA_PROFILES", ROOT / "config" / "profiles.json"))
EVIDENCE_DIR = Path(os.getenv("TRINETRA_EVIDENCE", ROOT / "evidence"))
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'trinetra.db'}")
DETECTOR = os.getenv("TRINETRA_DETECTOR", "auto")  # auto | yolo | yolox | off. Cameras with source "mock" use the simulated scene
MODELS_DIR = Path(os.getenv("TRINETRA_MODELS", ROOT / "models"))
YOLO_WEIGHTS = os.getenv("YOLO_WEIGHTS", "yolo26n.pt")
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "640"))
YOLO_DEVICE = os.getenv("YOLO_DEVICE") or None  # e.g. "0" for the first GPU, "cpu"
OPERATOR_TOKEN = os.getenv("OPERATOR_TOKEN", "")  # empty = no auth (localhost demo only)
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
ANALYSIS_FPS = float(os.getenv("ANALYSIS_FPS", "15"))  # upper limit; each camera also has its own max_fps
UPLOAD_DIR = Path(os.getenv("TRINETRA_UPLOADS", ROOT / "uploads"))  # uploaded videos (Camera 4); never served back
MAX_UPLOAD_MB = int(os.getenv("TRINETRA_MAX_UPLOAD_MB", "1024"))  # largest video the dashboard accepts
HOST = os.getenv("TRINETRA_HOST", "127.0.0.1")
PORT = int(os.getenv("TRINETRA_PORT", "8000"))
