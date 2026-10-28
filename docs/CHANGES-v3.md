# v3 changes: Camera 4 — Uploaded Video Tracking

The three original cameras, the five tabs, the detectors, tracking thresholds and the look of the dashboard are
unchanged. No new Python or Node packages; `start.bat` is unchanged.

## New files

| File | Purpose |
| --- | --- |
| `backend/trinetra/uploads.py` | Format check from the file's first bytes, decode check (OpenCV), safe storage (`uploads/<camera>/<random>.ext` + `meta.json`), the frame reader (video timestamps, frame skipping by video time) and the playback state machine with its command queue |
| `frontend/src/components/VideoPanel.jsx` | The Camera 4 controls: Upload (button or drag-and-drop, progress bar), Start processing, Pause, Resume, Restart, Stop, Remove (two clicks), Speed, progress `mm:ss / mm:ss`, people detected / tracked, processing fps, IN/OUT |
| `backend/tests/test_uploads.py` | 5 tests: sniffing, rejected uploads, the full control cycle and cleanup, incident video fields and de-duplication, real NanoDet tracking on an uploaded clip |
| `docs/CHANGES-v3.md` | This file |

## Modified files

| File | Change |
| --- | --- |
| `backend/trinetra/worker.py` | Per-frame pipeline moved into `_process()` (shared by every camera, behaviour unchanged); new `_upload_loop()` for `source: "upload"` (commands, pacing, end of video, idle pictures, video-time timeline); incidents get video fields and are not raised twice for the same moment of the same video |
| `backend/trinetra/main.py` | Endpoints `POST/GET/DELETE /api/cameras/{id}/video`, `POST …/video/control`, `GET …/video/timeline`; `/api/stats?scope=live\|video`; tracking stats and visits of an upload camera use its current run; Camera 4 added once to older configs; MJPEG stream sends the boundary after each picture and re-sends an idle picture every 2 s (idle cameras used to stay blank in the browser) |
| `backend/trinetra/db.py` | New nullable columns (incident: `source_kind`, `video_id`, `video_name`, `video_ts`, `video_end`; visits and crossings: `session_id`, video times), added automatically to existing databases; video-scoped queries |
| `backend/trinetra/detector.py` | `reset()` on each detector (Restart: fresh tracker, same model) |
| `backend/trinetra/evidence.py` | Optional frame time (clips of uploaded videos follow the video's clock); `reset()` |
| `backend/trinetra/analytics/risk.py`, `pipeline.py` | `close_all()` / `finish()`: close live incidents when a video ends, stops or restarts |
| `backend/trinetra/analytics/tracks.py` | Crossings and visit summaries also carry the tracker time (`t`, `started_t`, `ended_t`) |
| `backend/trinetra/analytics/overlay.py` | HUD can show the video position instead of the clock |
| `backend/trinetra/sources.py`, `siteconfig.py`, `config.py` | `upload` source kind; Camera 4 default config and one-time migration; `TRINETRA_UPLOADS`, `TRINETRA_MAX_UPLOAD_MB` |
| `config/site.json`, `site.default.json` | Camera 4 added |
| `frontend/src/components/CameraTile.jsx`, `pages/LivePage.jsx` | Camera 4 card with the video panel; uploaded-video cards stay last |
| `frontend/src/components/KpiStrip.jsx` | Live totals leave uploaded videos out; camera mix shown (live / sample clip / simulated / uploaded video) |
| `frontend/src/pages/TrackingPage.jsx`, `components/Charts.jsx`, `components/ActivityFeed.jsx` | Video controls on the Tracking page; charts and activity on the video's timeline (mm:ss) |
| `frontend/src/pages/AnalyticsPage.jsx` | Source selector: live cameras or Camera 4 (summary + 6–8 video charts + its incidents) |
| `frontend/src/pages/IncidentsPage.jsx`, `components/IncidentPanel.jsx`, `components/AlertQueue.jsx` | "▶ 00:18 in video", source and file name, duration on the video's clock, "recorded footage" note; CSV columns |
| `frontend/src/pages/SetupPage.jsx` | "Uploaded video" camera type; note when editing Camera 4's zones |
| `frontend/src/api.js`, `format.js`, `styles.css` | Upload (XHR with progress), video API, labels, `mmss()`, panel styles |
| `backend/tests/conftest.py`, `test_api.py` | Test site includes Camera 4 |
| `README.md`, `docs/CONTRACT.md`, `docs/demo-checklist.md`, `.env.example`, `.gitignore` | Documentation, settings, `uploads/` ignored |

## v3.1: Dense crowd mode (packed rooms filmed from above)

Prompted by a phone video of a packed hall where the default detector found almost no one.

| File | Change |
| --- | --- |
| `backend/trinetra/detector.py` | `CrowdDetector`: YOLOX-M on 5x4 overlapping enlarged tiles + one whole-frame pass, duplicate and fragment merging, ONNX Runtime when installed (`OnnxRunner`), camera-motion compensation; selected by camera option `model: "crowd"` |
| `backend/trinetra/tracking.py` | Optional switches (defaults unchanged): `rescue` (centre-distance matching), `predict_s` (motion extrapolation); `compensate()`; `CameraMotion` (optical flow + RANSAC similarity) |
| `backend/trinetra/analytics/tracks.py`, `overlay.py`, `worker.py` | No body-height speed estimate and compact `#ID` tags in Dense crowd mode; visits finalised after 6.5 s there |
| `backend/trinetra/siteconfig.py` | `options.model` accepts `crowd` |
| `models/yolox_m.onnx` | YOLOX-M (Apache-2.0), downloaded and SHA-256-checked if missing |
| `start.bat`, `start.sh` | Optional `onnxruntime` install (Dense crowd about 2x faster); failure does not stop the start |
| `backend/tools/process_video.py` | Track people in a video file and save an annotated MP4 + per-frame CSV (same pipeline as Camera 4) |
| `frontend/src/components/VideoPanel.jsx`, `ZoneEditor.jsx` | Detection selector on the Camera 4 card (Fast / Accurate / Dense crowd); Setup option |
| `backend/tests/test_crowd.py` | 7 tests: live defaults unchanged, pan compensation keeps IDs, no ID hand-over to a neighbour, seated people kept, motion estimate, no speed estimate, crowd detector beats Fast on small people |

## v3.2: Windows text fix

On Windows, Camera 4's name showed as "Camera 4 â€" Uploaded Video Tracking": Python read the UTF-8 settings files with
Windows' default character set (Windows-1252), which splits the dash "—" into three characters.

| File | Change |
| --- | --- |
| `backend/trinetra/config.py` | `read_text()`: UTF-8 (with or without a byte-order mark), falling back to Windows-1252 for files older versions wrote; `fix_mojibake()` repairs "â€"-style text; `.env` read the same way |
| `backend/trinetra/siteconfig.py` | `site.json` and `profiles.json` read and written as UTF-8; garbled names repaired on load (and saved back once) and in camera updates sent by a page opened before the fix |
| `backend/trinetra/uploads.py` | The uploaded video's `meta.json` read and written as UTF-8 (a file name in Hindi or with emoji no longer breaks an upload on Windows) |
| `backend/tools/*.py`, `eval/lead_time.py`, tests | Explicit UTF-8 everywhere |
| `frontend/src/components/VideoPanel.jsx`, `AnalyticsPage.jsx`, `styles.css` | Video-state badge classes prefixed (`vs-empty`), so the "NO VIDEO" badge no longer picks up the page's `.empty` padding |
| `backend/tests/test_encoding.py` | 5 tests: the Windows misreading and its repair, UTF-8 / BOM / old Windows-1252 files, repair saved to disk, garbled names in updates, video file names in any language |

## v3.3: ready for GitHub

| File | Change |
| --- | --- |
| `.gitignore` | Keeps private and large files out of the repository: `.env`, `trinetra.db`, `evidence/`, `uploads/`, `config/site.json` (may hold IP-camera passwords), every video file, `models/yolox_s.onnx`, `models/yolox_m.onnx`, `models/yolo26n.pt` (downloaded and checked on first use) |
| `.gitattributes` | `start.bat` always checked out with Windows line endings, `start.sh` with Unix ones; models and images treated as binary |
| `backend/trinetra/siteconfig.py` | Creates `config/site.json` from `site.default.json` when it is missing (a fresh copy from GitHub) |
| `README.md` | How to run a copy downloaded from GitHub |
