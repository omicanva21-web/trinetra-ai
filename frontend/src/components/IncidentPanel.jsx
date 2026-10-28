import { useEffect, useState } from 'react'
import { api, withToken } from '../api.js'
import { KIND_LABEL, STATUS_LABEL, clock, duration, mmss } from '../format.js'
import CrushClock from './CrushClock.jsx'
import { ZoneDensityChart } from './Charts.jsx'

const ACTIONS = [
  ['acknowledge', 'Acknowledge'], ['dispatch', 'Dispatch team'], ['false_alarm', 'False alarm'], ['resolve', 'Resolve'],
]
const DONE = { acknowledge: 'acknowledged', dispatch: 'dispatched', false_alarm: 'false_alarm', resolve: 'resolved' }

export default function IncidentPanel({ incident, zone, samples, thresholds, cameraName, onClose, onError, onChanged }) {
  const [detail, setDetail] = useState(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.incident(incident.id).then(setDetail).catch((e) => onError(e.message))
  }, [incident.id, incident.status, onError])

  const act = async (action) => {
    setBusy(true)
    try {
      const row = await api.act(incident.id, action, note)
      setNote('')
      setDetail(await api.incident(incident.id))
      onChanged?.(row)
    } catch (e) { onError(e.message) }
    setBusy(false)
  }
  const live = incident.active && zone
  const reasons = (live && zone.reasons?.length ? zone.reasons : incident.reasons) || []
  const v = Math.round(incident.updated_at)
  const closed = incident.status === 'resolved' || incident.status === 'false_alarm'

  return (
    <div className="panel">
      <div className="row">
        <button className="link" onClick={onClose}>← Back</button>
        <span className="spacer" />
        <span className={`badge lvl ${incident.level}`}>{incident.active ? `NOW ${incident.level}` : 'CLEARED'}</span>
        <span className="quiet">peak {incident.peak_level}</span>
      </div>
      <h2>{incident.zone_name}</h2>
      <p className="quiet">
        {KIND_LABEL[incident.kind] || incident.kind} · {cameraName(incident.camera_id)} ·{' '}
        {incident.video_ts != null
          ? <>at <b>{mmss(incident.video_ts)}</b> in the uploaded video{incident.video_name ? ` “${incident.video_name}”` : ''} (detected while processing at {clock(incident.started_at)})</>
          : <>started {clock(incident.started_at)}</>} · status <b>{STATUS_LABEL[incident.status]}</b>
      </p>
      {incident.source_kind === 'upload' && <div className="note">Recorded footage: this happened in the video, not live right now.</div>}
      {!incident.active && !closed && <div className="note">{incident.source_kind === 'upload' ? 'The video moved past this moment (or ended).' : 'The camera no longer sees this risk.'} Review the evidence, then resolve or mark it a false alarm.</div>}
      {incident.unsaved && <div className="note warn">Storage failed for this incident; it is shown live only.</div>}

      {incident.kind.startsWith('crowd') && incident.active && <CrushClock etaS={zone?.eta_s} trend={zone?.trend} big />}

      <h3>Why this alert {live ? '(live)' : '(at last update)'}</h3>
      {reasons.length ? (
        <ul className="reasons">
          {reasons.map((r) => (
            <li key={r.signal}><span>{r.text}</span><span className="bar"><i style={{ width: `${Math.min(100, r.points * 1.4)}%` }} /></span><b>+{r.points}</b></li>
          ))}
        </ul>
      ) : <p className="quiet small">No active risk signals now.</p>}

      {incident.kind.startsWith('crowd') && (
        <>
          <h3>Zone density ({incident.source_kind === 'upload' ? 'while processing, clock time' : 'live, last 30 minutes'})</h3>
          <ZoneDensityChart samples={samples} zoneId={incident.zone_id} thresholds={thresholds} height={160} />
        </>
      )}

      <h3>Evidence</h3>
      <div className="evidence">
        {incident.has_snapshot
          ? <img src={withToken(`/api/incidents/${incident.id}/snapshot?v=${v}`)} alt="Snapshot at the worst moment so far" />
          : <p className="quiet small">No snapshot saved.</p>}
        {incident.has_clip
          ? <video src={withToken(`/api/incidents/${incident.id}/clip`)} controls muted playsInline />
          : <p className="quiet small">The clip (5 s before and after) is saved about 5 s after the alert opens.</p>}
      </div>

      <h3>Response</h3>
      <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Note (optional): who was sent, what was found" />
      <div className="actions">
        {ACTIONS.map(([key, label]) => <button key={key} disabled={busy || closed} className={`btn ${key}`} onClick={() => act(key)}>{label}</button>)}
      </div>

      <h3>Log</h3>
      <ol className="log">
        <li>{clock(incident.started_at)} · opened by Trinetra{incident.video_ts != null ? ` (video position ${mmss(incident.video_ts)})` : ''}</li>
        {(detail?.actions || []).map((a) => (
          <li key={a.id}>{clock(a.ts)} · {STATUS_LABEL[DONE[a.action]]} (+{duration(a.ts - incident.started_at)}){a.note ? ` — ${a.note}` : ''}</li>
        ))}
      </ol>
    </div>
  )
}
