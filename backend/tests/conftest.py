"""Runs before any test module: point Trinetra at a temporary site, database and evidence folder."""
import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMP = Path(tempfile.mkdtemp())
site = json.loads((ROOT / "config" / "site.default.json").read_text(encoding="utf-8"))
site["cameras"] = [c for c in site["cameras"] if c["source"] in ("mock", "upload")]  # cam3 simulated, cam4 uploads
site["cameras"].append({"id": "cam9", "name": "Browser camera", "source": "browser", "enabled": True,
                        "options": {"max_fps": 15},
                        "zones": [{"id": "z1", "name": "Desk", "kind": "restricted",
                                   "polygon_norm": [[0.5, 0], [1, 0], [1, 1], [0.5, 1]]}],
                        "lines": [{"id": "l1", "name": "Door", "points_norm": [[0.5, 1], [0.5, 0]]}]})
(TMP / "site.json").write_text(json.dumps(site), encoding="utf-8")
shutil.copy(ROOT / "config" / "profiles.json", TMP / "profiles.json")
os.environ.update(DATABASE_URL=f"sqlite:///{TMP / 'test.db'}", TRINETRA_EVIDENCE=str(TMP / "evidence"),
                  TRINETRA_SITE=str(TMP / "site.json"), TRINETRA_PROFILES=str(TMP / "profiles.json"),
                  TRINETRA_DETECTOR="off", TRINETRA_UPLOADS=str(TMP / "uploads"), TRINETRA_MAX_UPLOAD_MB="5")
