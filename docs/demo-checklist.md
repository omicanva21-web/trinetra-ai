# Demo checklist v3 (run 1 hour before judging and again 10 minutes before)

## Machine
- [ ] Laptop on charger; sleep, screen saver and notifications off
- [ ] Zoom, Teams, Meet and the Camera app closed (they lock the webcam)
- [ ] Fresh numbers: close Trinetra, rename `trinetra.db` to `trinetra-old.db`, run `start.bat`
- [ ] One Chrome/Edge tab at http://localhost:8000, full screen; header badge says **Live**
- [ ] Profile in the header: **Demo profile** (say it is a demo profile when you show crowd alerts)
- [ ] Even light on the area in front of the webcam; nothing bright behind you
- [ ] Backups: a screen recording of the full demo and screenshots of each step

## Tracking page (the main demo)
| # | Action | Expected |
| --- | --- | --- |
| 1 | Open **Tracking** | Laptop webcam selected; your box with `#ID`, trail, time in view |
| 2 | If "No video": press **Use browser camera**, allow | Header: ● Camera streaming ~10–15 fps; tracking starts within 2–3 s |
| 3 | Walk across the Door line left → right | IN counter +1; Activity: "#N crossed Door line IN" |
| 4 | Step into the right third | Red box; table shows "Restricted strip · Ns"; Live tab badge +1 |
| 5 | Second person walks in | New ID, new colour; both in the table |
| 6 | Click the second person's row | White highlight and full path; others grey; "Stop following #N" |
| 7 | Both leave the view | After ~2 s: Activity shows "#N left after Ns"; Time-in-view chart updates |
| 8 | Switch camera to **Campus walkway** | Many IDs on real footage; walkway counter; movement paths |

## Camera 4: uploaded video (the judges' request)
| # | Action | Expected |
| --- | --- | --- |
| U1 | Live tab → Camera 4 card → **Upload video** → pick an MP4 of people walking | Card: READY, file name, `00:00 / mm:ss`, first frame with "Ready" |
| U2 | **Start processing** | PROCESSING; boxes with `#ID` on the card; progress bar moves; People detected / tracked / fps update |
| U3 | Click the video → Tracking page | "Video tracking", same controls, table of IDs, charts on video time (mm:ss) |
| U4 | **Pause**, wait, **Resume** | Position holds while paused, then continues from the same point |
| U5 | **Restart** | Back to 00:00, IDs start again from #1 (new run) |
| U6 | Analytics → Source: Camera 4 | Summary + charts for the video only; live totals untouched |
| U7 | Let it finish (or Speed: Max) | COMPLETED, 100 %; incidents (if zones were drawn) show "▶ mm:ss in video" |
| U8 | **Remove** (click twice) | Card back to NO VIDEO; upload another file |

Prepare: a 30–60 s MP4 with several people walking, saved on the desktop. **A packed room filmed from above
(hall, auditorium)?** Set the card's **Detection → Dense crowd** and process it fully *before* judging (a few seconds
per frame on a laptop); during the demo, Restart it at Speed Max or show the finished results on Tracking/Analytics. For alerts, draw a restricted zone on
Camera 4 in Setup after uploading it (saving restarts the camera: press Start processing again).

## Rest of the system
| # | Action | Expected |
| --- | --- | --- |
| 9 | Live tab → click the restricted-zone alert | Reasons name the ID ("(#N)"), snapshot, clip after ~5 s |
| 10 | Dispatch team with a note, then Resolve | Logged with times; card leaves the queue |
| 11 | Analytics tab | Footbridge (SIMULATED) density chart with the Crush Clock |
| 12 | Setup → Edit zones on the webcam | Zones and the Door line with its IN arrow on the still frame |
| 13 | Close the black window for 5 s, run start.bat again | Page shows Reconnecting…, then recovers by itself |
