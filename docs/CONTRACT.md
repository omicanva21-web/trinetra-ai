# Trinetra API and message contract (v3)

Zones, counting lines and calibration points are stored as fractions of the frame (`polygon_norm`, `points_norm`,
`image_points_norm`, 0 to 1), so they work at any camera resolution.

## Detection (detector → analytics)

```json
{"id": 17, "cls": "person", "box": [412.3, 188.0, 438.9, 252.6], "conf": 0.81}
```

`cls` is `person` or `vehicle`. `id` is the tracking ID, or `null` while a track is unconfirmed (drawn grey, not counted).

## REST

Token = header `X-Operator-Token` or query `token`, required only when `OPERATOR_TOKEN` is set in `.env`.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/health` | | `{ok, profile, detector_mode, cameras:[{id,status,fps,detector}]}` |
| GET | `/api/config` | | site, profile, profile labels, thresholds, cameras, `auth_required` |
| GET | `/api/cameras` | | cameras with zones, lines, options, status, detector, fps, frame size, `browser_connected` |
| POST · PUT · DELETE | `/api/cameras` · `/api/cameras/{id}` | camera body | add / update (worker restarts) / delete (token) |
| GET | `/api/cameras/{id}/frame.jpg` | | latest clean frame (token) |
| GET | `/api/cameras/{id}/tracks?recent=40` | | `{active:[{id,cls,age_s,path}], finished:[visit], summary}` |
| POST | `/api/cameras/{id}/focus` | `{"track_id": 7}` or `{"track_id": null}` | follow a person on the video |
| GET | `/api/tracking/stats?camera_id=cam1&window_min=30` | | people, vehicles, avg/median/longest time in view, IN/OUT totals and per line, per-minute crossings, dwell histogram, zone visits |
| GET · PUT · POST | `/api/profiles` · `/api/profiles/{name}` · `/api/profile` | | thresholds (token for changes) |
| GET | `/api/incidents?status=&level=&camera_id=&limit=` | | incidents, newest first |
| GET · POST | `/api/incidents/{id}` · `/api/incidents/{id}/action` | `{"action":"acknowledge\|dispatch\|false_alarm\|resolve","note":""}` | incident + log (token for actions) |
| GET | `/api/incidents/{id}/snapshot` · `/clip` | | JPEG · H.264 MP4 (token) |
| GET | `/api/metrics?minutes=10` · `/api/stats?scope=all\|live\|video&camera_id=&video_id=` | | 1 Hz history per camera (incl. `tracked`, `unique`, line counts) · incident statistics (`live` leaves out uploaded-video incidents; `video` = one camera / one video). `live.people` never includes uploaded videos |
| GET | `/stream/{id}.mjpg` | | live annotated MJPEG for an `<img>` (token as `?token=`); an unchanged picture is re-sent every 2 s |

### Uploaded video (cameras whose `source` is `upload`, e.g. Camera 4)

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| POST | `/api/cameras/{id}/video` | the video file as the raw body (`Content-Type: application/octet-stream`), header `X-Filename` (URL-encoded, display only) | video status (token). 400 empty · 409 still processing / another upload running · 413 over `TRINETRA_MAX_UPLOAD_MB` · 415 not a readable MP4/MOV/AVI/MKV/WEBM · 507 disk full |
| GET | `/api/cameras/{id}/video` | | video status (below) |
| POST | `/api/cameras/{id}/video/control` | `{"action": "start\|pause\|resume\|restart\|stop\|speed", "speed": 1}` | video status (token); 409 with a reason when the action does not apply now |
| DELETE | `/api/cameras/{id}/video` | | stops processing, deletes the file → `state: "empty"` (token) |
| GET | `/api/cameras/{id}/video/timeline` | | `{session, duration_s, samples:[{vt, people, tracked, unique, in, out, fps, zones:{id:{count,density,score}}}]}`, one sample per second of video for the current run |

Video status (also in every `state` message of the camera as `video`, and in `/api/cameras` as `video`):

```json
{"state": "processing", "message": "", "file": "gate_cam_0612.mp4", "container": "mp4", "codec": "h264",
 "size_bytes": 2096452, "width": 768, "height": 576, "video_fps": 10.0, "duration_s": 40.0,
 "position_s": 12.4, "progress": 0.31, "analysis_fps": 9.8, "realtime": 0.98, "speed": 1.0,
 "frames_analysed": 124, "session": "e601568c-2-4f1a9c", "session_started": 1793121000.2,
 "uploaded_at": 1793120990.1, "video_id": "e601568cc357fc61e3f584e94c1da6b9", "max_upload_mb": 1024,
 "accepted": "MP4, MOV, AVI, MKV or WEBM"}
```

- `state`: `empty` · `ready` · `processing` · `paused` · `completed` · `stopped` · `error` (reason in `message`).
- `position_s` is time in the video (decoder timestamps; variable frame rate is followed). `analysis_fps` is frames
  analysed per second of processing; `realtime` is video seconds processed per second (1.0 = real time).
- `speed`: 0.25 / 0.5 / 1 / 2 / 4 / 8, or 0 = as fast as the computer can. Pacing never runs ahead of the chosen speed;
  a slower computer plays the video slower, analysing at most `max_fps` frames per second of video.
- `video_id` is a SHA-256 prefix of the file's content, so an identical file uploaded again is the same video.
- `session` identifies one processing run (Start or Restart). Tracking statistics, finished visits and the timeline of
  an uploaded-video camera always refer to the current run, on the video's timeline (`/api/tracking/stats` returns
  `"axis": "video"`, `bucket_s`, and `t` in video seconds).

Incidents from an uploaded video carry `source_kind: "upload"`, `video_id`, `video_name`, `video_ts` (seconds into the
video when it started) and `video_end` (last update, video seconds). `started_at` is when Trinetra detected it while
processing. An incident that matches one already stored for the same video and zone within ±5 s of video time
(a re-run) is not raised again. When a video finishes, stops or restarts, its live incidents are closed (`active: false`).

Camera body:

```json
{"name": "Gate camera", "source": "0", "enabled": true,
 "options": {"max_fps": 15, "model": "fast", "heatmap": false, "trails": true},
 "zones": [{"id": "z1", "name": "Restricted strip", "kind": "restricted", "base_score": 75, "dwell_limit_s": 8,
            "polygon_norm": [[0.66, 0], [1, 0], [1, 1], [0.66, 1]]}],
 "lines": [{"id": "l1", "name": "Door line", "points_norm": [[0.5, 1], [0.5, 0]]}],
 "calibration": null}
```

`options.model`: `fast` (NanoDet), `accurate` (YOLOX-S) or `crowd` (tiled YOLOX-M for packed rooms filmed from above; slow).
`source`: `0`/`1` webcam index, `browser`, `upload` (videos uploaded from the dashboard), a video file path (relative to the project folder), an `rtsp://` or `http://` URL, or `mock`.
A counting line A→B counts IN when the feet move from its negative to its positive side (the arrow on the video points to IN); reversing the two points swaps IN and OUT.

Finished visit (`finished[]`, stored in the `trackrecord` table):

```json
{"track_id": 39, "cls": "person", "started_at": 1793100000.0, "ended_at": 1793100019.6, "duration_s": 19.6,
 "distance_m": 23.98, "estimated": true, "avg_speed": 1.22, "max_speed": 1.9, "zones": ["Main walkway"],
 "crossings": [{"line": "Walkway counter", "dir": "out"}], "path": [[0.41, 0.52], [0.43, 0.51]]}
```

## WebSockets

`/ws` (server → dashboard):

| `type` | When | Content |
| --- | --- | --- |
| `hello` | on connect | profile, thresholds, latest `states`, open `incidents` |
| `state` | every 0.5 s per camera | people, vehicles, score, level, fps, status, detector, zones, and `tracking`: `{active:[{id,cls,age_s,zones:[{name,kind,s}],speed,est,dist,state,conf,pos}], active_count, unique, finished, avg_dwell_s, longest_s, lines:[{id,name,in,out}], focus}` |
| `incident` | an incident changes | `action` + the incident |
| `track_event` | a line crossing or a finished visit | `event: "crossing"` (`line_name`, `direction`, `track_id`, `wall`) or `event: "track_done"` (visit summary without path). Uploaded video: also `video_ts` (seconds into the video) and `session` |
| `camera_status` | a camera fails, retries or waits for the browser camera | status text |
| `profile` · `config_changed` | thresholds / cameras changed | |

`/ws/camera/{id}` (dashboard → server): binary JPEG frames from the browser's camera, only for cameras whose source is `browser` (token as `?token=`). The server analyses the newest frame and drops the rest.
