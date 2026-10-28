"""Windows showed "Camera 4 â€” Uploaded Video Tracking": UTF-8 files read with Windows' default code page.
These tests reproduce that and check that every text file is read and written as UTF-8 and old damage is repaired."""
import json

from conftest import TMP  # noqa: F401  (temporary site created before any trinetra import)

from trinetra import config, siteconfig, uploads  # noqa: E402

NAME = "Camera 4 — Uploaded Video Tracking"


def test_the_windows_bug_and_its_repair():
    garbled = NAME.encode("utf-8").decode("cp1252")  # what Python on Windows read before the fix
    assert garbled == "Camera 4 â€” Uploaded Video Tracking"
    assert config.fix_mojibake(garbled) == NAME
    for ok in (NAME, "Gate camera", "Café", "प्रवेश द्वार", "Zone 3 · 2 m²"):
        assert config.fix_mojibake(ok) == ok  # correct text is never touched


def test_read_text_utf8_bom_and_old_cp1252(tmp_path):
    p = tmp_path / "a.json"
    p.write_bytes(json.dumps({"name": NAME}, ensure_ascii=False).encode("utf-8"))
    assert json.loads(config.read_text(p))["name"] == NAME
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"name": NAME}, ensure_ascii=False).encode("utf-8"))  # Notepad BOM
    assert json.loads(config.read_text(p))["name"] == NAME
    p.write_bytes('{"name": "Café"}'.encode("cp1252"))  # written by an older version on Windows
    assert json.loads(config.read_text(p))["name"] == "Café"


def test_site_file_with_garbled_names_is_repaired_and_saved_as_utf8(tmp_path, monkeypatch):
    site = tmp_path / "site.json"
    garbled = NAME.encode("utf-8").decode("cp1252")
    site.write_text(json.dumps({"profile": "demo", "cameras": [{"id": "cam4", "name": garbled, "source": "upload",
                                                                 "zones": [{"name": "Hall — left"}]}]},
                               ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "SITE_FILE", site)
    loaded = siteconfig.load_site()
    assert loaded["cameras"][0]["name"] == NAME and loaded["cameras"][0]["zones"][0]["name"] == "Hall — left"
    raw = site.read_bytes()
    assert "—".encode("utf-8") in raw and "â€".encode("utf-8") not in raw  # repaired on disk, as UTF-8
    siteconfig.save_site(loaded)
    assert json.loads(site.read_bytes().decode("utf-8"))["cameras"][0]["name"] == NAME


def test_camera_update_with_a_garbled_name_is_repaired():
    body = siteconfig.CameraIn(name=NAME.encode("utf-8").decode("cp1252"), source="upload")
    assert siteconfig.camera_to_store("cam4", body)["name"] == NAME


def test_video_meta_keeps_any_file_name(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    store = uploads.VideoStore("cam7")
    part = tmp_path / "x.part"
    part.write_bytes(b"\0" * 16)
    meta = {"id": "a" * 32, "container": "mp4", "name": "हॉल का वीडियो — 27 Oct 😀.mp4"}
    store.replace(part, meta)
    got, path = store.current()
    assert got["name"] == meta["name"] and path.name == "a" * 32 + ".mp4"
    assert json.loads((store.dir / "meta.json").read_bytes().decode("utf-8"))["name"] == meta["name"]
