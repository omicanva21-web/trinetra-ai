# Trinetra AI — Live Tracking Prototype (v3: + Camera 4, uploaded video tracking)

**Every CCTV camera, an intelligent first responder.** Team Tech Avengers · CODE YUDH, Chandigarh University

Trinetra watches live camera feeds, including your **laptop webcam**, detects people and vehicles, gives every person
an anonymous **tracking ID**, and follows them in real time: their path, time in view, walking speed, the zones they
enter, and whether they cross a **counting line** (IN / OUT). On top of that it measures crowd density, counts down to
dangerous density (the **Crush Clock**), detects restricted-zone entry and loitering, and puts every alert in one
ranked, explained queue with a snapshot and a video clip. Everything runs on your laptop at `http://localhost:8000`.
No cloud, no face recognition.

**New in v3 — Camera 4, Uploaded Video Tracking:** upload a recording (MP4, MOV, AVI, MKV or WEBM) from the dashboard
and Trinetra runs the **same real detector and tracker** on it, with Start, Pause, Resume, Restart, Stop and Remove,
a progress bar, video-time charts, and incidents stamped with the moment in the video. The three original cameras
are unchanged.

> **Seeing only one "SIMULATED" camera and no tabs at the top?** That is the old *starter kit*. Unzip this version
> into a **new folder** and run its `start.bat`. It has five tabs: Live, Tracking, Analytics, Incidents, Setup.

---

## 1. Start it (Windows) — 3 steps

1. **Install Python 3.11** from <https://www.python.org/downloads/> if you don't have it. In the installer, tick **"Add python.exe to PATH"**.
2. **Unzip** `trinetra-v3-video-upload.zip` (right-click → *Extract All…*) into a new folder, for example `C:\trinetra3` (avoid OneDrive folders).
3. **Close Zoom, Teams, Meet and the Camera app** (they lock the webcam), then **double-click `start.bat`**.

The first run creates a private Python environment and installs packages (2–5 minutes, internet needed once) and
downloads an 8 MB sample video. Then your browser opens **http://localhost:8000** by itself. Keep the black window
open; closing it stops Trinetra. Later starts take a few seconds. Use **Chrome or Edge**, and **one** dashboard tab.
v3 needs **no new packages**: if you already ran v2, the same steps work.

> **Coming from v2?** Your v2 folder keeps working. To keep v2's history and zones, copy v2's `trinetra.db` and
> `config\site.json` into the v3 folder before starting: Trinetra adds Camera 4 to that `site.json` and the new columns
> to that database by itself (your data is kept).
>
> **Got it from GitHub?** Use **Code → Download ZIP** (or `git clone`), then the same steps. The repository leaves out
> the large models (YOLOX-S, YOLOX-M) and Ultralytics' YOLO26 weights; Trinetra downloads each one the first time it is
> needed and checks it against its SHA-256 (internet needed once). `config/site.json` is created from
> `site.default.json` on the first start.
>
> macOS / Linux: run `./start.sh` in a terminal instead. Trinetra listens only on your own machine (127.0.0.1).

## 2. Camera 4 — track people in an uploaded video (step by step)

1. **Open the dashboard** (http://localhost:8000). On the **Live** tab, the last card is
   **Camera 4 — Uploaded Video Tracking**, marked `UPLOADED VIDEO`, with the status `NO VIDEO`.
2. **Press Upload video** and pick a recording from your computer, or **drag the file onto the card**.
   Accepted: **MP4, MOV, AVI, MKV, WEBM**, up to **1024 MB** (change `TRINETRA_MAX_UPLOAD_MB` in `.env`).
   A green bar shows the upload; then Trinetra **checks the file by decoding its first frames** (the file name does not
   matter: a renamed document is refused). The card then says **READY**, shows the file name, the duration
   (`00:00 / 02:30`) and the first frame.
3. **Press Start processing.** Every analysed frame goes through the detector, the tracker and the analytics.
   The card shows boxes with **#IDs**, the progress bar moves, and below it you see **People detected** (now),
   **People tracked** (unique this run), **Processing fps**, the counting-line **IN / OUT** totals and the playback rate.
4. **Controls** (buttons that do not apply right now are greyed out):

   | Button | What it does |
   | --- | --- |
   | **Pause** | Stops processing and playback at the current moment; the picture and the people table stay as they were |
   | **Resume** | Continues from exactly the paused position |
   | **Restart** | Starts again from 00:00 as a new run: IDs start again at #1, counts and charts reset |
   | **Stop** | Ends the run and closes the video file (results stay visible). *Start processing* then runs it again from the beginning |
   | **Remove** | Click twice: stops, deletes the uploaded file and returns the card to *Upload video* |
   | **Speed** | 0.5× · 1× real time (default) · 2× · 4× · **Max** (as fast as the computer can) |

   If the computer is slower than the chosen speed, the video simply plays slower: every analysed frame is still
   processed in order, and all times stay **positions in the video**, not clock times.
5. **See the results:**
   - **Tracking** tab (or click the video on the card) → *Video tracking*: the same controls, the processed video, the
     table of people (ID, time in view, zone, speed, distance, state), click a person to follow them, charts on the
     video's timeline (mm:ss), movement paths, and an activity feed such as `▶ 01:12 #7 crossed Counting line IN`.
   - **Analytics** tab → **Source: Camera 4 — Uploaded Video Tracking**: a summary (file, progress, processing rate,
     unique people, IN/OUT, time in view, incidents from this video) and charts of people detected, unique people,
     processing rate, entries/exits, people per zone and density over the video.
   - **Incidents** tab: alerts from the video say `▶ 00:18 in video · processed 22:42` and *Uploaded video: file.mp4*.
6. **Upload another video** once the run is finished or stopped (Upload is greyed out while processing: press Stop first).

**Packed room filmed from above? Use Dense crowd.** The default *Fast* detector is made for people walking past
a camera at eye level. In a hall full of seated people filmed from a balcony, people are only 15–60 px tall and half
hidden by tables and laptops, and *Fast* finds almost no one. On the Camera 4 card set **Detection → Dense crowd**
(while the video is not processing), then press **Start processing**. Dense crowd cuts every frame into 20 overlapping
tiles, enlarges each one and runs the larger YOLOX-M model on it, follows the camera's own movement (handheld phone
videos), and keeps seated people tracked. It is slow by design: a few seconds per frame on a laptop (it analyses 3 frames
per second of video), so prepare the video before the demo. On a 62 s phone video of a packed hackathon hall it
tracked 66 people per frame on average (52–80 most of the time, up to 93) where *Fast* found none (see section 8). It still misses people who are almost
completely hidden or blend into white tablecloths; counts in such scenes are a lower bound.
Speeds are not shown in this mode (body height says nothing about metres when filmed from above), and a counting
line only works with a camera that does not move.

**Zones for your video.** Camera 4 starts with a "Whole view" gathering area (counts people; no floor size, so no
density alerts) and a vertical counting line in the middle. For alerts, go to **Setup → Camera 4 → Edit zones** after
uploading: draw a **restricted zone**, enter the gathering area's real size in m² for density, or move the counting line.
Saving restarts the camera, so press **Start processing** again afterwards.

What is real and what is not: the uploaded video uses the **real** detector and tracker (the same as the webcam). Its
numbers are **kept separate** from the live totals at the top (*People in view* and *Unique people* count live,
simulated and sample-clip feeds only). Tracking IDs are per run of one video; people are **not** matched across
videos or cameras. If the same file is uploaded or re-run again, incidents already stored for the same moment are not
raised twice.

## 3. Live webcam tracking — what to do

1. Open the **Tracking** tab. It shows **Laptop webcam (live)** by default.
2. **If you see yourself with a coloured box and an ID tag (#1)** — it works. Trinetra opened the webcam directly.
3. **If you see "No video · cannot open webcam 0"**, press **Use browser camera** in the yellow bar. The browser asks
   for camera permission once (click **Allow**); the webcam picture is then streamed to Trinetra from the browser.
   The header shows **● Camera streaming … fps**. Keep that tab open and visible.

What you see on the Tracking page:

| Part | What it shows |
| --- | --- |
| **Live video** | Every tracked person: colour box, tag `#ID · seconds in view · speed`, a trail of where they walked in the last 4 s, red box when inside a restricted zone. Grey thin boxes are detections not yet confirmed. The counting line (yellow) has an **IN** arrow and live totals. Top-right: LIVE clock (VIDEO position for Camera 4), analysed fps, people tracked now, unique people. |
| **Counters** | Tracked now · Unique people · Entered (IN) · Left (OUT) · Average time in view · Longest in view now |
| **People in view table** | ID (same colour as on the video), time in view, current zone and how long they have been in it, speed (m/s), distance walked, state (moving / still / hidden behind something) |
| **Follow a person** | Click a row, or click a person in the video: they get a white highlight and their full path; everyone else is greyed out. Following stops by itself when they leave. |
| **Charts** | People tracked over time · Entries and exits per minute · Time-in-view distribution |
| **Movement paths** | A still frame with the paths of the last 40 people who left (thin) and people in view now (bold) |
| **Activity** | Live feed: "#7 crossed Door line IN", "#7 left after 34 s · 12 m · was in Restricted strip" |
| **Zone visits** | How many people entered each zone in the last 30 minutes |

The default webcam layout (change it on Setup → Edit zones):

| Area of the picture | Type | What happens |
| --- | --- | --- |
| Left 62 % "Gathering area" | Crowd zone, 2 m² | 3 people in it for a few seconds = **HIGH** crowd alert (demo profile: danger line 1.5 people/m²) |
| Right third "Restricted strip" | Restricted zone | Step in → **HIGH** alert with your snapshot within seconds; the longer you stay, the more points the dwell reason adds (limit 8 s) |
| Vertical line in the middle "Door line" | Counting line | Walk left → right = **IN**, right → left = **OUT** |

## 4. Demo script for the judges (about 4 minutes)

1. **Tracking tab, webcam.** "Every person gets an anonymous ID; no face recognition." Walk into view: `#1` appears with a trail.
2. **Walk across the Door line** left to right: the IN counter goes up and the Activity feed says "#1 crossed Door line IN".
3. **Step into the right third:** the box turns red, the Live tab badge counts a HIGH alert, the table shows "Restricted strip · 3s".
4. **Ask a judge to walk in too.** Two IDs, two colours. Click the judge's row: Trinetra follows them (white box, full path).
5. **Live tab → click the alert:** reasons with points ("1 inside restricted zone (#1) +75", "dwell 9 s"), snapshot, 10-second clip. Press **Dispatch team** with a note; it is logged.
6. **Camera 4: upload a recording** (a 30–60 s MP4 of people walking, prepared on the desktop) → **Start processing**.
   "Same AI, any footage: CCTV exports, phone videos." Show the IDs, **Pause / Resume**, then open it in **Tracking**.
7. **Analytics → Source: Camera 4:** the video's own charts on its timeline, kept apart from the live totals.
8. **Analytics → live cameras:** the Crush Clock on the simulated footbridge (labelled SIMULATED) counting down before the danger line.

## 5. The five pages

- **Live:** KPI strip (live totals; the uploaded video is listed in *Cameras running* but not added to people counts), camera wall (riskiest first, Camera 4 last so its buttons never move; each tile shows tracked / unique people, line counts and a risk bar per zone; click a tile to open it in Tracking), and the alert queue with the incident panel.
- **Tracking:** sections 2 and 3.
- **Analytics:** a **Source** selector: *live, simulated and sample-clip cameras* (people over time per camera, live risk by zone, density with the Crush Clock, alerts per 5 minutes, incidents by level and type, response performance) or *Camera 4* (section 2).
- **Incidents:** full history with filters, evidence, the same incident panel, **Export CSV** (with source, video file and video time columns).
- **Setup:** cameras (status, detector, fps, enable, delete); **Add a camera** (webcam, browser camera, video file, IP camera, simulated, uploaded video); **Edit zones**: draw zones, **draw counting lines** (2 clicks; *Swap IN/OUT* flips the direction), calibrate the floor, choose the detector (**Fast** / **Accurate**), max fps, trails and heat overlay; **Alert thresholds**.

## 6. Detectors and tracking

| Detector | When it is used | Notes |
| --- | --- | --- |
| **NanoDet-Plus** (bundled, 3.8 MB) | Cameras set to **Fast** (default, also Camera 4) | About 9× less compute than YOLOX: smooth tracking on a laptop CPU |
| **YOLOX-S** (bundled, 36 MB) | Cameras set to **Accurate** | Better for small, distant people; more CPU |
| **YOLOX-M on tiles** (bundled, 101 MB) | Cameras set to **Dense crowd** | Packed rooms filmed from above; ~20 model runs per frame; uses ONNX Runtime when installed (about 2× faster) |
| **YOLO26n + ByteTrack** (optional) | Every camera except Dense crowd, after `install_yolo.bat` | Best accuracy; needs PyTorch. If it fails to load, Trinetra falls back automatically |

How tracking works (NanoDet / YOLOX): each frame the tracker predicts where everyone should be (constant velocity),
matches confident detections by box overlap, rescues fast movers by distance, then uses weak detections to keep
half-hidden people tracked (the ByteTrack idea). A track gets an ID only after two matches **and** one strong detection,
so one-frame glitches and weak look-alikes (cones, posts, bins) never get IDs; an ID that never moves and scores weakly
for 4 s is dropped as a static object. A person hidden for up to 1.5 s keeps the same ID. The **feet** (bottom-centre of
the box) decide zones and line crossings; a crossing counts only when the feet go from clearly one side of the line to
clearly the other, so someone standing on the line is not counted twice. Speeds are in metres when the floor is
calibrated, otherwise estimated from body height (shown with ≈). Every finished visit is stored (time in view, distance,
zones, crossings, path) for the charts.

For an uploaded video the tracker's clock is the **video's own timeline** (decoder timestamps, so variable-frame-rate
phone videos are handled), so speeds, dwell times and the 1.5 s occlusion rule mean the same as on a live camera, at
any processing speed. Camera 4 analyses up to 15 frames per second of video (its *max fps* in Setup); skipped frames
are only decoded, not analysed. The model is loaded once per camera; Restart only resets the tracker.

## 7. Settings (`.env` in the project folder)

| Setting | Default | Meaning |
| --- | --- | --- |
| `TRINETRA_DETECTOR` | `auto` | `auto` (YOLO26 if installed, else per-camera Fast/Accurate), `yolo`, `yolox`, `nanodet`, `off` |
| `ANALYSIS_FPS` | `15` | upper limit of analysed frames per second for every camera (each camera also has its own limit in Setup) |
| `TRINETRA_MAX_UPLOAD_MB` | `1024` | largest video Camera 4 accepts |
| `TRINETRA_UPLOADS` | `uploads` | folder for uploaded videos (one per uploaded-video camera; deleted by *Remove*) |
| `YOLO_IMGSZ` / `YOLO_DEVICE` | `640` / auto | YOLO26 input size; `0` = first NVIDIA GPU, `cpu` = force CPU |
| `TRINETRA_PORT` | `8000` | if busy, the next free port is used and printed |
| `OPERATOR_TOKEN` | empty | require a token for actions, uploads, evidence, streams and setup; enter it on the Setup page |

Restart Trinetra after editing `.env` (an existing `.env` from v2 works; the new settings then use their defaults).

## 8. What was tested, honestly

All tests below were run on a 2-core Linux cloud machine (no GPU, no webcam), with the bundled NanoDet detector.

| Part | Status |
| --- | --- |
| **Dense crowd mode on a real phone video** (62 s, handheld, 854×480, a packed hackathon hall filmed from a balcony) | Through the dashboard: with *Fast*, **0 people** in the first 7 s (the problem you reported); after switching the card to *Dense crowd* (the video stayed loaded) 49 people detected and 52 tracked within 6 frames, Stop answered at once during a slow frame, 0 browser errors. Whole video with the same pipeline (`process_video.py`): 188 frames analysed, **66 people per frame with an ID on average** (median 67, 52–80 for 80 % of frames, max 93), 5.3–5.5 s per frame on the 2-core test machine with ONNX Runtime. The 219 "unique" IDs are **not a headcount**: an ID breaks when someone is missed for more than 6 s. Counting-line totals are not meaningful here because the camera moves |
| Backend automated tests | **38 pass** (21 from v2 + 5 upload + 5 text encoding + 7 dense crowd: live defaults unchanged, camera pan keeps IDs with motion compensation, no ID hand-over to a neighbour, seated people kept, motion estimate, no fake speeds, crowd detector finds people 17–28 px tall that Fast misses). Upload tests: file-type sniffing; rejection of empty, renamed-text, truncated and oversized uploads and of uploads to a non-video camera; the whole control cycle (upload → first frame → start → pause holds the position → resume → restart = new run → stop → speed → run to the end → timeline → video-scoped stats → remove deletes the file); one processing thread only; incident video times and duplicate detection; **real NanoDet + tracker on an uploaded pedestrian clip** (IDs kept for 5+ s, clock = video time) |
| **Camera 4 end to end in a real browser** (headless Chromium, the dashboard as a user would use it) | **51 of 51 checks pass**: 4 cards (original 3 unchanged), all tabs; text file and over-limit file refused with clear messages; renamed document refused by the server; MP4 uploaded, file name and duration shown, stored under a server-made name; first frame shown; zones saved without losing the video; processing with real boxes and `#IDs` on the card and the Tracking page; pause holds the position, resume continues, restart starts a new run, stop, Max speed to the end (100 %); charts and activity on video time; other cameras kept running; Analytics separates live and video; incident shows `▶ 00:18 in video`, the evidence photo and clip, and "recorded footage"; Remove deletes the file; a second video (WEBM) processed; the same file uploaded again was recognised (no duplicate incident); fits a phone screen; no unexpected browser errors |
| Video formats | Decoded and accepted: MP4 (H.264), MOV, MKV, WEBM (VP8), AVI (MPEG-4). Processed end to end in the browser: MP4, WEBM; a MOV accepted by **drag-and-drop** onto the card. Variable frame rate: timestamps follow the file (checked on a VFR test file) |
| Large file | 157 MB, 5 min 18 s MP4: uploaded in 1.1 s locally, server memory +14 MB (streamed to disk); processing at Max: 1.8× real time; memory flat at ≈570 MB |
| Speed on the test machine (2 cores, 3 other cameras running) | 1× = 1.01× real time, Max = 1.6–1.8× real time. With a browser also rendering four video streams on the same 2 cores, 1× fell to 0.42–0.63× real time — still every frame of the 10 fps video analysed, in order |
| Upgrade from v2 | A v2 `site.json` (no Camera 4) and a v2 database (138 visits, 159 crossings, 3 incidents) were upgraded automatically on start; data kept. An uploaded video survives a server restart (back as READY) |
| v2 features after the change | Browser-camera live tracking test re-run: IDs, following, line counts, charts, paths, activity — 0 errors. The 21 v2 tests still pass |
| Earlier v2 results (not repeated for v3) | Real footage served as a live IP-camera stream: 15 fps analysed, 33 visits stored; switching a camera between direct and browser mode 4 times; Setup line drawing and the Accurate detector live |
| **Your laptop webcam opened directly** | **Not tested here** (the cloud machine has no camera). If it fails, the browser-camera path is the tested fallback |
| **`start.bat` / `install_yolo.bat` on Windows** | **Not executed here** (Linux test machine); `start.sh` was run from a clean unzip of v2. v3 changed no packages or launchers |
| **YOLO26 + ByteTrack** | **Not run here** (PyTorch too large for the test machine); falls back automatically |
| Not tried | H.265/HEVC, AV1 and ProRes files (decoding depends on the codecs inside OpenCV; a file it cannot decode is refused with a message to re-export as MP4 H.264). The longest video processed to the end was 40 s (the 5-minute file was processed for 20 s) |

## 9. Troubleshooting

| What you see | Fix |
| --- | --- |
| Only one SIMULATED camera, no tabs | You are running the old starter kit. Use this folder's `start.bat` |
| No **Camera 4** card | Check that you started *this* folder's `start.bat` (the black window shows its path); on Setup, Camera 4 may be disabled: tick *Enabled* |
| **Upload video** button does nothing / greyed out | Greyed out while a video is processing or paused: press **Stop** first. Otherwise reload the page (Ctrl+F5) |
| "not a supported video" / "could not be decoded" | Use MP4, MOV, AVI, MKV or WEBM. Phone videos in HEVC/H.265 and some screen recordings may not decode: re-export as **MP4 (H.264)**, e.g. with the free VLC (*Media → Convert / Save*) or Clipchamp |
| "larger than the … MB limit" | Trim the video, or raise `TRINETRA_MAX_UPLOAD_MB` in `.env` and restart |
| **No people detected** (or only a few) | People are small, seated or filmed from above: on the Camera 4 card set **Detection → Dense crowd** and Start processing again (section 2). Footage too dark or people seen from straight above can still fail. Check the card does not say *Person detection is not available* |
| Tracking IDs not appearing (grey boxes only) | A person needs two matches and one confident detection before an ID is given; very small or blurry people may stay grey. Try **Accurate**, or a closer/clearer video |
| Dense crowd is very slow | Expected: about 20 model runs per frame. Let `start.bat` install ONNX Runtime (about 2× faster; the black window says if it could not), close other heavy apps, and process the video before the demo |
| Video processing is slow | Normal on a laptop CPU: the video plays slower but every analysed frame is processed. Speed it up: disable cameras you don't need (Setup), keep Camera 4 on **Fast**, lower its max fps, close other heavy apps. *Max* speed uses all the CPU |
| Card says **ERROR** | The message says why (e.g. the file is damaged half-way). Press **Restart**, or **Remove** and upload again |
| Webcam: **No video · cannot open webcam 0** | Close Zoom/Teams/Camera; Windows Settings → Privacy & security → Camera → allow desktop apps; or press **Use browser camera** on the Tracking page; or try source `1` (USB webcam) on Setup |
| Browser camera: **permission blocked** | Click the camera icon in the address bar → Allow → press Start camera again |
| Browser camera: **camera busy** | Another app or Trinetra's direct webcam has it. Close the app, or keep the camera in browser mode only |
| Browser camera slows to ~1 fps | The tab is hidden or minimised. Keep it visible (browsers throttle hidden tabs) |
| Low fps / jerky boxes | Keep cameras on **Fast**, disable cameras you don't need on Setup (each one shares your CPU), lower max fps |
| Backend errors / page says **Reconnecting…** | The black Trinetra window was closed or crashed: read its last lines, then run `start.bat` again |
| **Port conflict** (another program uses 8000) | Trinetra picks the next free port by itself and prints it (e.g. `http://localhost:8001`) and opens that; or set `TRINETRA_PORT` in `.env` |
| `Python was not found` / packages broken | Install Python 3.11 from python.org with "Add python.exe to PATH" (the Microsoft Store shortcut does not count). Broken packages: delete `backend\.venv` and run `start.bat` again (it reinstalls) |
| Page stuck loading with several dashboard tabs open | Browsers allow ~6 live video streams per site: use one Trinetra tab |
| Names show odd characters such as `Camera 4 â€" Uploaded` | Fixed in v3.2 (Windows read the settings file in the wrong character set). Start v3.2: it repairs names saved that way by itself |
| Reset everything | Copy `config/site.default.json` over `config/site.json`; delete `trinetra.db` and the `uploads` folder |

## 10. For developers

```bash
# backend (from the backend folder, with backend/.venv activated)
pip install -r requirements.txt        # adds Ultralytics and the test tools
python -m pytest -q                    # 38 tests
python run.py                          # same as start.bat, from a terminal

# dashboard with live reload (Node.js 22+), proxying to the backend on :8000
cd frontend && npm install && npm run dev          # http://localhost:5173
npm run build                                      # updates frontend/dist, served by the backend
```

Track people in a video file without the dashboard and save an annotated MP4 + per-frame CSV (same pipeline as Camera 4):
`python backend/tools/process_video.py my_video.mp4 --model crowd --fps 3`.
Measure a clip (Crush Clock lead time + tracking results): `python eval/lead_time.py --camera cam2 --profile station`.
Check zones and lines: `python backend/tools/check_zones.py`. API and message formats: `docs/CONTRACT.md`.

How Camera 4 plugs in: a camera whose `source` is `upload` gets an `UploadController` (`uploads.py`) inside its normal
`CameraWorker`. The API only queues commands; the worker thread applies them between frames, so one camera can never
run two processing loops and only that thread touches the file. Each frame goes through the same `_process` step as
every other camera (detector → tracker → zones/risk → track registry → overlay → evidence → incidents), with the
video's timestamp as the clock. Uploads arrive as a raw request body (no extra package), are streamed to
`uploads/incoming/*.part`, checked (magic bytes + decoding), then moved to `uploads/<camera>/<random>.ext`; they are
never served back over HTTP.

```text
trinetra/
├── start.bat · start.sh · install_yolo.bat     launchers
├── backend/
│   ├── run.py                    starts the server and opens the browser
│   ├── trinetra/
│   │   ├── main.py               REST, WebSockets, streams, setup, tracking, analytics, video upload endpoints
│   │   ├── worker.py             one thread per camera: frame → detect → track → analyse → draw → store (+ upload loop)
│   │   ├── uploads.py            Camera 4: format checks, safe storage, video reader, playback controls
│   │   ├── sources.py            webcam / IP camera (newest frame), browser camera, video files, simulation
│   │   ├── detector.py           YOLO26 + ByteTrack, NanoDet (fast), YOLOX-S (accurate), tiled YOLOX-M (dense crowd)
│   │   ├── tracking.py           ByteTrack-style tracker with look-alike filtering; camera-motion compensation
│   │   ├── analytics/tracks.py   paths, time in view, speed, zones, counting lines, visit summaries
│   │   ├── analytics/            calibration, zones, Crush Clock, risk engine, overlay
│   │   └── siteconfig.py db.py hub.py evidence.py config.py mock_scene.py
│   └── tests/                    38 tests
├── frontend/                     React + Recharts dashboard (dist/ is pre-built; VideoPanel.jsx = Camera 4 card)
├── config/                       site.json, site.default.json, profiles.json
├── models/                       nanodet_plus_m_416.onnx, yolox_s.onnx, yolox_m.onnx, yolo26n.pt, licences
├── uploads/                      created on the first upload (not in the zip)
├── clips/ · evidence/ · eval/ · docs/
```

## 11. Honest limits and licences

- Very dense crowds are undercounted by any box detector, so density reads low there. Dense crowd mode finds many more
  people but still misses fully hidden ones; for exact head counts a crowd-counting model would be needed.
- IDs are per camera and per run; there is no identity matching across cameras or videos (by design: no face recognition).
- Two people who cross very close can occasionally swap IDs; someone hidden for more than 1.5 s gets a new ID.
- Speeds without floor calibration are estimates from body height.
- The Crush Clock assumes the recent trend continues; it is a warning to act, not a prediction.
- Uploaded videos are processed one run at a time per camera; for two videos at once, add a second *Uploaded video* camera on Setup (each uses CPU).
- A video's alerts appear in the alert queue (labelled recorded footage) and must be closed by an operator like any other.
- The simulated feed is a simulation. Say so whenever it is shown.
- NanoDet-Plus and YOLOX models: Apache-2.0 (via OpenCV Zoo). Ultralytics YOLO26: AGPL-3.0. Sample video: OpenCV public samples.
