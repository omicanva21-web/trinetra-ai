"""SQLite storage for incidents, operator actions, finished tracks and line crossings
(SQLModel; PostgreSQL works via DATABASE_URL)."""
from __future__ import annotations

import json
import threading
import time

from sqlalchemy import inspect, text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from . import config

STATUSES = {"open", "acknowledged", "dispatched", "false_alarm", "resolved"}
ACTIONS = {"acknowledge": "acknowledged", "dispatch": "dispatched", "false_alarm": "false_alarm", "resolve": "resolved"}


class Incident(SQLModel, table=True):
    id: str = Field(primary_key=True)
    camera_id: str
    zone_id: str
    zone_name: str
    kind: str
    level: str
    peak_level: str = "LOW"
    score: int = 0
    peak_score: int = 0
    reasons_json: str = "[]"
    metrics_json: str = "{}"
    status: str = "open"
    active: bool = True
    started_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    snapshot_path: str | None = None
    clip_path: str | None = None
    # uploaded videos: where in the recording it happened (started_at is when Trinetra detected it)
    source_kind: str | None = None
    video_id: str | None = None
    video_name: str | None = None
    video_ts: float | None = None
    video_end: float | None = None  # last update, in video seconds (duration on the video's own clock)

    def public(self) -> dict:
        d = self.model_dump(exclude={"reasons_json", "metrics_json", "snapshot_path", "clip_path"})
        d["reasons"] = json.loads(self.reasons_json)
        d["metrics"] = json.loads(self.metrics_json)
        d["has_snapshot"] = bool(self.snapshot_path)
        d["has_clip"] = bool(self.clip_path)
        return d


class IncidentAction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    incident_id: str = Field(index=True)
    action: str
    actor: str = "operator"
    note: str = ""
    ts: float = Field(default_factory=time.time)


class TrackRecord(SQLModel, table=True):
    """One person or vehicle from first to last sighting on one camera."""
    id: int | None = Field(default=None, primary_key=True)
    camera_id: str = Field(index=True)
    track_id: int
    object_class: str  # person | vehicle ("cls" would clash with SQLModel internals)
    started_at: float
    ended_at: float = Field(index=True)
    duration_s: float
    distance_m: float = 0.0
    estimated: bool = True
    avg_speed: float = 0.0
    max_speed: float = 0.0
    zones_json: str = "[]"
    crossings_json: str = "[]"
    path_json: str = "[]"
    session_id: str | None = Field(default=None, index=True)  # uploaded video: one processing run
    video_start: float | None = None  # seconds into the video
    video_end: float | None = None

    def public(self) -> dict:
        d = self.model_dump(exclude={"zones_json", "crossings_json", "path_json", "object_class"})
        d.update(cls=self.object_class, zones=json.loads(self.zones_json), crossings=json.loads(self.crossings_json),
                 path=json.loads(self.path_json))
        return d


class Crossing(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    camera_id: str = Field(index=True)
    line_id: str
    line_name: str
    direction: str  # in | out
    track_id: int
    ts: float = Field(index=True)
    session_id: str | None = Field(default=None, index=True)
    video_ts: float | None = None


class Store:
    """All DB writes go through one lock: SQLite allows one writer at a time."""

    def __init__(self, url: str = config.DB_URL):
        args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=args)
        SQLModel.metadata.create_all(self.engine)
        self._add_new_columns()
        self.lock = threading.Lock()

    def _add_new_columns(self) -> None:
        """Older trinetra.db files lack the uploaded-video columns: add them (data is kept)."""
        insp = inspect(self.engine)
        with self.engine.begin() as conn:
            for model in (Incident, TrackRecord, Crossing):
                table = model.__tablename__
                have = {c["name"] for c in insp.get_columns(table)}
                for col in model.__table__.columns:
                    if col.name not in have:
                        kind = "FLOAT" if col.type.python_type is float else "VARCHAR"
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col.name} {kind}'))
                        if col.index:
                            conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col.name} ON {table} ({col.name})"))

    def upsert_from_event(self, event: dict, wall_started: float, extra: dict | None = None) -> dict:
        inc = event["incident"]
        with self.lock, Session(self.engine) as s:
            row = s.get(Incident, inc["id"])
            if row is None:
                row = Incident(id=inc["id"], camera_id=inc["camera_id"], zone_id=inc["zone_id"],
                               zone_name=inc["zone_name"], kind=inc["kind"], level=inc["level"],
                               started_at=wall_started, **{k: v for k, v in (extra or {}).items() if k != "video_end"})
            if event["action"] == "reopened" and row.status in {"acknowledged", "dispatched"}:
                pass  # keep the operator's status; the incident is live again
            row.level = inc["level"]
            row.peak_level = inc.get("peak_level", inc["level"])
            row.kind = inc["kind"]
            row.score = int(inc["score"])
            row.peak_score = int(inc.get("peak_score", inc["score"]))
            row.reasons_json = json.dumps(inc.get("reasons", []))
            row.metrics_json = json.dumps(inc.get("metrics", {}))
            row.active = bool(inc.get("active", True))
            row.updated_at = time.time()
            if extra and extra.get("video_end") is not None:
                row.video_end = extra["video_end"]
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.public()

    def set_evidence(self, incident_id: str, snapshot: str | None = None, clip: str | None = None) -> dict | None:
        with self.lock, Session(self.engine) as s:
            row = s.get(Incident, incident_id)
            if row is None:
                return None
            if snapshot:
                row.snapshot_path = snapshot
            if clip:
                row.clip_path = clip
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.public()

    def act(self, incident_id: str, action: str, note: str = "", actor: str = "operator") -> dict | None:
        with self.lock, Session(self.engine) as s:
            row = s.get(Incident, incident_id)
            if row is None:
                return None
            row.status = ACTIONS[action]
            row.updated_at = time.time()
            s.add(row)
            s.add(IncidentAction(incident_id=incident_id, action=action, note=note, actor=actor))
            s.commit()
            s.refresh(row)
            return row.public()

    def get(self, incident_id: str) -> Incident | None:
        with Session(self.engine) as s:
            return s.get(Incident, incident_id)

    def find_video_incident(self, camera_id: str, video_id: str, zone_id: str, video_ts: float,
                            tolerance_s: float = 5.0) -> dict | None:
        """An incident already reported for the same moment of the same uploaded video (re-run of the video)."""
        with Session(self.engine) as s:
            q = select(Incident).where(Incident.camera_id == camera_id, Incident.video_id == video_id,
                                       Incident.zone_id == zone_id, Incident.video_ts >= video_ts - tolerance_s,
                                       Incident.video_ts <= video_ts + tolerance_s)
            row = s.exec(q).first()
            return row.public() if row else None

    def list(self, status: str | None = None, limit: int = 100, level: str | None = None,
             camera_id: str | None = None) -> list[dict]:
        with Session(self.engine) as s:
            q = select(Incident)
            if status == "open":
                q = q.where(Incident.status.in_(["open", "acknowledged", "dispatched"]))
            elif status:
                q = q.where(Incident.status == status)
            if level:
                q = q.where(Incident.peak_level == level)
            if camera_id:
                q = q.where(Incident.camera_id == camera_id)
            rows = s.exec(q.order_by(Incident.started_at.desc()).limit(limit)).all()
            return [r.public() for r in rows]

    def stats(self, window_min: int = 60, bucket_min: int = 5, scope: str = "all", camera_id: str | None = None,
              video_id: str | None = None) -> dict:
        """Numbers for the Analytics page. Response times use the first operator action on each incident.
        scope: all | live (leave out uploaded-video incidents) | video (one camera, optionally one video)."""
        now = time.time()
        with Session(self.engine) as s:
            q = select(Incident)
            if scope == "live":
                q = q.where((Incident.source_kind.is_(None)) | (Incident.source_kind != "upload"))
            if camera_id:
                q = q.where(Incident.camera_id == camera_id)
            if video_id:
                q = q.where(Incident.video_id == video_id)
            incs = s.exec(q.order_by(Incident.started_at.desc()).limit(5000)).all()
            acts = s.exec(select(IncidentAction).order_by(IncidentAction.ts)).all()
        first_act, closed_at = {}, {}
        for a in acts:
            first_act.setdefault(a.incident_id, a.ts)
            if a.action in ("resolve", "false_alarm"):
                closed_at.setdefault(a.incident_id, a.ts)
        by_level = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
        by_kind, by_status, by_camera = {}, {}, {}
        respond, resolve_t = [], []
        n_buckets = window_min // bucket_min
        start = now - window_min * 60
        timeline = [{"t": round(start + i * bucket_min * 60), "MEDIUM": 0, "HIGH": 0} for i in range(n_buckets)]
        for inc in incs:
            by_level[inc.peak_level] = by_level.get(inc.peak_level, 0) + 1
            by_kind[inc.kind] = by_kind.get(inc.kind, 0) + 1
            by_status[inc.status] = by_status.get(inc.status, 0) + 1
            by_camera[inc.camera_id] = by_camera.get(inc.camera_id, 0) + 1
            if inc.id in first_act:
                respond.append(first_act[inc.id] - inc.started_at)
            if inc.id in closed_at:
                resolve_t.append(closed_at[inc.id] - inc.started_at)
            if inc.started_at >= start and inc.peak_level in ("MEDIUM", "HIGH"):
                i = min(n_buckets - 1, int((inc.started_at - start) // (bucket_min * 60)))
                timeline[i][inc.peak_level] += 1
        n_false = by_status.get("false_alarm", 0)
        reviewed = n_false + by_status.get("resolved", 0)

        def avg(xs):
            return round(sum(xs) / len(xs), 1) if xs else None

        return {"total": len(incs), "open": sum(by_status.get(k, 0) for k in ("open", "acknowledged", "dispatched")),
                "by_level": by_level, "by_kind": by_kind, "by_status": by_status, "by_camera": by_camera,
                "avg_response_s": avg(respond), "avg_resolve_s": avg(resolve_t), "responded": len(respond),
                "false_alarm_rate": round(n_false / reviewed, 3) if reviewed else None,
                "timeline": timeline, "bucket_min": bucket_min}

    # ------------------------------------------------------------------ tracking
    def save_track(self, camera_id: str, summary: dict, session_id: str | None = None) -> None:
        video = {"session_id": session_id, "video_start": summary.get("started_t"),
                 "video_end": summary.get("ended_t")} if session_id else {}
        with self.lock, Session(self.engine) as s:
            s.add(TrackRecord(camera_id=camera_id, track_id=summary["track_id"], object_class=summary["cls"], **video,
                              started_at=summary["started_wall"], ended_at=summary["ended_wall"],
                              duration_s=summary["duration_s"], distance_m=summary["distance_m"],
                              estimated=summary["estimated"], avg_speed=summary["avg_speed"],
                              max_speed=summary["max_speed"], zones_json=json.dumps(summary["zones"]),
                              crossings_json=json.dumps(summary["crossings"]),
                              path_json=json.dumps(summary["path"][-120:])))
            s.commit()

    def save_crossing(self, camera_id: str, ev: dict, session_id: str | None = None) -> None:
        video = {"session_id": session_id, "video_ts": ev.get("t")} if session_id else {}
        with self.lock, Session(self.engine) as s:
            s.add(Crossing(camera_id=camera_id, line_id=ev["line_id"], line_name=ev["line_name"],
                           direction=ev["direction"], track_id=ev["track_id"], ts=ev["wall"], **video))
            s.commit()

    def tracking_stats(self, camera_id: str | None, window_min: int = 60, bucket_min: int = 1,
                       session: str | None = None, until_s: float = 0.0) -> dict:
        """Live cameras: the last `window_min` minutes on the clock. Uploaded video (`session`): one processing
        run of the video, bucketed by time in the video ("axis": "video", `t` in video seconds)."""
        now = time.time()
        start = now - window_min * 60
        with Session(self.engine) as s:
            if session:
                tq = select(TrackRecord).where(TrackRecord.session_id == session)
                cq = select(Crossing).where(Crossing.session_id == session)
            else:
                tq = select(TrackRecord).where(TrackRecord.ended_at >= start)
                cq = select(Crossing).where(Crossing.ts >= start)
            if camera_id:
                tq = tq.where(TrackRecord.camera_id == camera_id)
                cq = cq.where(Crossing.camera_id == camera_id)
            tracks = s.exec(tq).all()
            crossings = s.exec(cq).all()
        if session:
            end = max([until_s, 1.0] + [t.video_end or 0 for t in tracks] + [c.video_ts or 0 for c in crossings])
            bucket_s = next((b for b in (5, 10, 15, 30, 60, 120, 300, 600, 1800) if end / b <= 60), 3600)
            n_buckets = int(end // bucket_s) + 1
            timeline = [{"t": i * bucket_s, "in": 0, "out": 0} for i in range(n_buckets)]
            slot = lambda c: min(n_buckets - 1, int((c.video_ts or 0) // bucket_s))  # noqa: E731
        else:
            n_buckets = max(1, window_min // bucket_min)
            timeline = [{"t": round(start + i * bucket_min * 60), "in": 0, "out": 0} for i in range(n_buckets)]
            slot = lambda c: min(n_buckets - 1, int((c.ts - start) // (bucket_min * 60)))  # noqa: E731
        lines: dict[str, dict] = {}
        for c in crossings:
            timeline[slot(c)][c.direction] += 1
            ln = lines.setdefault(c.line_id, {"id": c.line_id, "name": c.line_name, "in": 0, "out": 0})
            ln[c.direction] += 1
        bins = [(0, 5), (5, 15), (15, 30), (30, 60), (60, 120), (120, None)]
        people = [t for t in tracks if t.object_class == "person"]
        hist = [{"label": f"{a}-{b}s" if b else f"{a}s+", "count": sum(1 for t in people if t.duration_s >= a and
                                                                         (b is None or t.duration_s < b))}
                for a, b in bins]
        durations = sorted(t.duration_s for t in people)
        zone_visits: dict[str, int] = {}
        for t in people:
            for z in json.loads(t.zones_json):
                zone_visits[z] = zone_visits.get(z, 0) + 1
        extra = {"axis": "video", "bucket_s": bucket_s, "session": session} if session else {"axis": "clock"}
        return {**extra, "window_min": window_min, "bucket_min": bucket_min, "people": len(people),
                "vehicles": len(tracks) - len(people),
                "avg_dwell_s": round(sum(durations) / len(durations), 1) if durations else None,
                "median_dwell_s": durations[len(durations) // 2] if durations else None,
                "longest_s": durations[-1] if durations else None,
                "total_in": sum(1 for c in crossings if c.direction == "in"),
                "total_out": sum(1 for c in crossings if c.direction == "out"),
                "lines": list(lines.values()), "timeline": timeline, "dwell_hist": hist, "zone_visits": zone_visits}

    def recent_tracks(self, camera_id: str, limit: int = 50, session: str | None = None) -> list[dict]:
        with Session(self.engine) as s:
            q = select(TrackRecord).where(TrackRecord.camera_id == camera_id)
            if session:
                q = q.where(TrackRecord.session_id == session)
            q = q.order_by(TrackRecord.ended_at.desc()).limit(limit)
            return [r.public() for r in s.exec(q).all()]

    def actions(self, incident_id: str) -> list[dict]:
        with Session(self.engine) as s:
            q = select(IncidentAction).where(IncidentAction.incident_id == incident_id).order_by(IncidentAction.ts)
            return [a.model_dump() for a in s.exec(q).all()]
