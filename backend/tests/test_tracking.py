"""Tracker and track-registry behaviour on scripted movements (no video needed)."""
from trinetra.analytics.tracks import TrackRegistry
from trinetra.analytics.zones import ZoneMonitor
from trinetra.tracking import ByteTrackLite


def person(x, y, conf=0.9, w=40, h=100):
    """A detection whose feet are at (x, y)."""
    return {"id": None, "cls": "person", "conf": conf, "box": [x - w / 2, y - h, x + w / 2, y]}


def run(tracker, frames, dt=0.1):
    """frames: list of detection lists; returns the tracker output per frame."""
    return [tracker.update([dict(d) for d in dets], i * dt) for i, dets in enumerate(frames)]


def ids(out):
    return [d["id"] for d in out]


def test_walking_person_keeps_one_id():
    frames = [[person(100 + 12 * i, 300)] for i in range(40)]  # 120 px/s for 4 s
    outs = run(ByteTrackLite(), frames)
    assert ids(outs[0]) == [None]  # first sighting is tentative
    assert {i for out in outs[1:] for i in ids(out)} == {1}


def test_one_frame_false_detection_never_gets_an_id():
    frames = [[person(100 + 12 * i, 300)] for i in range(10)]
    frames[5].append(person(600, 200))  # appears for one frame only
    outs = run(ByteTrackLite(), frames)
    assert {i for out in outs for i in ids(out) if i is not None} == {1}


def test_brief_occlusion_keeps_the_same_id():
    frames = []
    for i in range(50):
        hidden = 20 <= i < 30  # behind a pillar for 1 s
        frames.append([] if hidden else [person(100 + 12 * i, 300)])
    outs = run(ByteTrackLite(), frames)
    assert {i for out in outs[30:] for i in ids(out)} == {1}


def test_weak_detections_keep_a_half_hidden_person_tracked():
    frames = [[person(100 + 12 * i, 300, conf=0.9 if i < 10 else 0.3)] for i in range(30)]
    outs = run(ByteTrackLite(), frames)
    assert {i for out in outs[10:] for i in ids(out)} == {1}


def test_two_people_passing_each_other_keep_their_ids():
    frames = [[person(100 + 15 * i, 300), person(700 - 15 * i, 330)] for i in range(40)]
    outs = run(ByteTrackLite(), frames)
    first = {round(d["box"][0]): d["id"] for d in outs[2]}  # A starts on the left, B on the right
    a_id, b_id = first[min(first)], first[max(first)]
    last = outs[-1]
    a_last = min(last, key=lambda d: d["box"][1])  # A walks at y=300 (higher on screen)
    b_last = max(last, key=lambda d: d["box"][1])
    assert a_last["id"] == a_id and b_last["id"] == b_id


def make_registry(lines=None, zones=None):
    zone_objs = [ZoneMonitor(z, None) for z in (zones or [])]
    return TrackRegistry((1000, 600), None, zone_objs, lines or [])


DOOR = {"id": "l1", "name": "Door", "points": [[500, 600], [500, 0]]}  # IN = left to right


def feed(reg, xs, y=400, tid=1, dt=0.1, t0=0.0):
    events = []
    for i, x in enumerate(xs):
        d = person(x, y)
        d.update(id=tid, foot=(x, y))
        events += reg.update(t0 + i * dt, 1000.0 + t0 + i * dt, [d])
    return events


def test_line_counts_in_then_out():
    reg = make_registry([DOOR])
    ev = feed(reg, list(range(300, 701, 20)))  # left to right
    ev += feed(reg, list(range(700, 299, -20)), t0=3.0)  # and back
    crossings = [e["direction"] for e in ev if e["type"] == "crossing"]
    assert crossings == ["in", "out"]
    line = reg.snapshot()["lines"][0]
    assert (line["in"], line["out"]) == (1, 1)


def test_standing_on_the_line_is_not_counted():
    reg = make_registry([DOOR])
    jitter = [496, 503, 498, 504, 497, 502] * 10  # feet wobble around x = 500
    ev = feed(reg, jitter)
    assert not [e for e in ev if e["type"] == "crossing"]


def test_finished_track_summary_has_duration_path_and_zones():
    zone = {"id": "z1", "name": "Gate", "kind": "restricted", "polygon": [[600, 0], [1000, 0], [1000, 600], [600, 600]]}
    reg = make_registry([DOOR], [zone])
    feed(reg, list(range(300, 801, 10)))  # 5 s walk, ends inside the Gate zone
    snap = reg.snapshot()
    assert snap["active"][0]["zones"][0]["name"] == "Gate" and snap["unique"] == 1
    done = [e for e in reg.update(9.0, 1009.0, []) if e["type"] == "track_done"]  # gone for > 2 s
    assert len(done) == 1
    s = done[0]
    assert 4.5 <= s["duration_s"] <= 5.5 and "Gate" in s["zones"] and len(s["path"]) >= 8
    assert s["crossings"] == [{"line": "Door", "dir": "in"}]
    assert s["estimated"] is True and 2.0 < s["distance_m"] < 12.0  # 500 px at 100 px per 1.7 m


def test_weak_static_lookalike_never_gets_an_id():
    tracker = ByteTrackLite(high=0.45, new_track=0.45, confirm_conf=0.6)
    frames = [[person(100 + 12 * i, 300, conf=0.8), person(800, 200, conf=0.47)] for i in range(50)]  # a cone at 0.47
    outs = run(tracker, frames)
    cone_ids = {d["id"] for out in outs for d in out if d["box"][0] > 700}
    assert cone_ids == {None}
    assert {d["id"] for out in outs[1:] for d in out if d["box"][0] < 700} == {1}


def test_static_lookalike_that_scores_high_once_is_demoted():
    tracker = ByteTrackLite(high=0.45, new_track=0.45, confirm_conf=0.6)
    reg = make_registry()
    frames = [[person(800, 200, conf=0.65 if i == 3 else 0.47)] for i in range(80)]  # a sign: one 0.65 spike, never moves
    demoted = None
    for i, dets in enumerate(frames):
        out = tracker.update([dict(d) for d in dets], i * 0.1)
        for d in out:
            d["foot"] = ((d["box"][0] + d["box"][2]) / 2, d["box"][3])
            demoted = d.get("demoted", demoted)
            if d.get("demoted") is not None:
                reg.discard(d["demoted"])
        reg.update(i * 0.1, 1000 + i * 0.1, [d for d in out if d["id"] is not None])
    assert demoted == 1 and all(d["id"] is None for d in out)
    assert reg.snapshot()["unique"] == 0 and not reg.active


def test_person_standing_still_is_not_demoted():
    tracker = ByteTrackLite(high=0.45, new_track=0.45, confirm_conf=0.6)
    outs = run(tracker, [[person(400, 300, conf=0.85)] for _ in range(100)])  # 10 s, perfectly still
    assert {d["id"] for d in outs[-1]} == {1}
