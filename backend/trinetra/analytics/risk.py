"""Explainable risk score per zone, levels, and incident lifecycle with hysteresis."""
from __future__ import annotations

import uuid

LEVELS = ["LOW", "MEDIUM", "HIGH"]


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def level_for(score: float) -> str:
    return "HIGH" if score >= 70 else "MEDIUM" if score >= 35 else "LOW"


def fmt_eta(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def assess_crowd(m: dict, p: dict) -> tuple[float, list[dict]]:
    """Points: density up to 40, Crush Clock up to 35, surge up to 15, pressure up to 10."""
    reasons, score = [], 0.0
    rho = m.get("density")
    if rho is not None:
        start = 0.5 * p["density_warn"]
        pts = 40 * clamp((rho - start) / (p["density_danger"] - start))
        score += pts
        reasons.append({"signal": "density", "points": round(pts),
                        "text": f"density {rho:.2f}/m² (warn {p['density_warn']}, danger {p['density_danger']})"})
    eta = m.get("eta_s")
    if eta is not None:
        pts = 35 * clamp(1 - eta / p["eta_alert_s"])
        score += pts
        reasons.append({"signal": "eta", "points": round(pts),
                        "text": f"rising {m.get('slope_per_min')}/m² per min, ETA {fmt_eta(eta)} to danger"})
    speed = m.get("speed")
    if speed is not None and m["count"] >= 3:
        ratio = m.get("surge_ratio", 1.0)
        pts = 15 * max(clamp((ratio - 1.3) / 0.7), clamp(speed / p["speed_surge_mps"]) if speed >= p["speed_surge_mps"] else 0)
        if pts > 0:
            score += pts
            reasons.append({"signal": "surge", "points": round(pts),
                            "text": f"speed {speed:.2f} m/s ({ratio:.1f}× normal)"})
    pressure = m.get("pressure")
    if pressure is not None:
        pts = 10 * clamp(pressure / p["pressure_ref"])
        if pts >= 1:
            score += pts
            reasons.append({"signal": "pressure", "points": round(pts),
                            "text": f"crowd pressure {pressure:.3f}/s² (reference {p['pressure_ref']})"})
    # Hard rules: never let the weighted sum hide a crossed danger line or an imminent one.
    if rho is not None and rho >= p["density_danger"]:
        score = max(score, 75)
    if eta is not None and eta <= 30:
        score = max(score, 70)
    return min(score, 100.0), sorted(reasons, key=lambda r: -r["points"])


def assess_restricted(m: dict, p: dict, zone_cfg: dict) -> tuple[float, list[dict]]:
    if m["count"] == 0:
        return 0.0, []
    base = float(zone_cfg.get("base_score", 55))
    limit = float(zone_cfg.get("dwell_limit_s", p["dwell_limit_s"]))
    who = f" ({', '.join(f'#{i}' for i in m.get('ids', []))})" if m.get("ids") else ""
    reasons = [{"signal": "intrusion", "points": round(base),
                "text": f"{m['count']} inside restricted zone{who}"}]
    score = base
    if m.get("has_vehicle"):
        score += 10
        reasons.append({"signal": "vehicle", "points": 10, "text": "vehicle in zone"})
    dwell_pts = 30 * clamp(m["max_dwell_s"] / limit)
    if dwell_pts >= 1:
        score += dwell_pts
        reasons.append({"signal": "dwell", "points": round(dwell_pts),
                        "text": f"dwell {m['max_dwell_s']:.0f} s (limit {limit:.0f} s)"})
    extra = min(15, 5 * (m["count"] - 1))
    if extra:
        score += extra
        reasons.append({"signal": "group", "points": extra, "text": f"{m['count']} people together"})
    return min(score, 100.0), sorted(reasons, key=lambda r: -r["points"])


class IncidentTracker:
    """Turns per-zone levels into incidents without alarm spam.

    - opens only after a level >= MEDIUM lasts `confirm_s`
    - escalates in place; sends throttled updates while active
    - clears after LOW lasts `clear_s`
    - re-triggers within `merge_s` of clearing reuse the same incident unless an operator closed it
    """

    def __init__(self, camera_id: str, confirm_s=1.0, clear_s=10.0, merge_s=60.0, update_every_s=2.0):
        self.camera_id = camera_id
        self.confirm_s, self.clear_s, self.merge_s, self.update_every_s = confirm_s, clear_s, merge_s, update_every_s
        self.zone_state: dict[str, dict] = {}
        self.operator_closed: set[str] = set()

    def step(self, t: float, zone_id: str, zone_name: str, kind: str, score: float,
             reasons: list, metrics: dict) -> list[dict]:
        st = self.zone_state.setdefault(zone_id, {"above_since": None, "below_since": None,
                                                    "incident": None, "last_sent": 0.0, "cleared_at": None})
        level = level_for(score)
        events = []
        inc = st["incident"]
        if inc and inc["id"] in self.operator_closed:
            st["incident"], inc = None, None
        if level != "LOW":
            st["below_since"] = None
            st["above_since"] = st["above_since"] if st["above_since"] is not None else t
            if inc is None and t - st["above_since"] >= self.confirm_s:
                prev = st.get("last_incident")
                if prev and st["cleared_at"] and t - st["cleared_at"] <= self.merge_s and prev["id"] not in self.operator_closed:
                    inc, action = prev, "reopened"
                else:
                    inc = {"id": uuid.uuid4().hex[:8], "camera_id": self.camera_id, "zone_id": zone_id,
                           "zone_name": zone_name, "kind": kind, "started_at": t, "peak_score": 0.0}
                    action = "opened"
                st["incident"] = inc
                peak = inc.get("peak_level", "LOW")
                inc.update(active=True, level=level, score=round(score), reasons=reasons, metrics=metrics, updated_at=t,
                           peak_level=level if LEVELS.index(level) > LEVELS.index(peak) else peak)
                inc["peak_score"] = round(max(inc["peak_score"], score))
                st["last_sent"] = t
                events.append({"action": action, "incident": dict(inc)})
            elif inc is not None:
                # Escalate only above the highest level already reported, so MEDIUM<->HIGH flicker does not re-alert.
                escalated = LEVELS.index(level) > LEVELS.index(inc["peak_level"])
                inc.update(level=level, score=round(score), reasons=reasons, metrics=metrics, updated_at=t, active=True)
                if escalated:
                    inc["peak_level"] = level
                inc["peak_score"] = round(max(inc["peak_score"], score))
                if escalated or t - st["last_sent"] >= self.update_every_s:
                    st["last_sent"] = t
                    events.append({"action": "escalated" if escalated else "updated", "incident": dict(inc)})
        else:
            st["above_since"] = None
            st["below_since"] = st["below_since"] if st["below_since"] is not None else t
            if inc is not None and t - st["below_since"] >= self.clear_s:
                inc.update(active=False, level=level, score=round(score), reasons=reasons, metrics=metrics, updated_at=t)
                events.append({"action": "cleared", "incident": dict(inc)})
                st["last_incident"], st["incident"], st["cleared_at"] = inc, None, t
        return events

    def close_all(self, t: float) -> list[dict]:
        """The footage ended (uploaded video finished or stopped): nothing is live any more."""
        events = []
        for st in self.zone_state.values():
            inc = st["incident"]
            if inc is not None:
                inc.update(active=False, updated_at=t)
                events.append({"action": "cleared", "incident": dict(inc)})
                st["last_incident"], st["incident"], st["cleared_at"] = inc, None, t
        return events
