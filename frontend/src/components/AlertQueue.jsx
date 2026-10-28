import CrushClock from './CrushClock.jsx'
import { KIND_LABEL, STATUS_LABEL, ago, mmss } from '../format.js'

export default function AlertQueue({ incidents, liveZone, onSelect, cameraName }) {
  return (
    <div className="queue">
      <h2>Alert queue <span className="count">{incidents.length}</span></h2>
      {!incidents.length && <p className="empty">No open incidents. All zones normal.</p>}
      <ol>
        {incidents.map((inc) => {
          const z = inc.active ? liveZone(inc) : null
          const reasons = (z?.reasons?.length ? z.reasons : inc.reasons || []).slice(0, 3)
          return (
            <li key={inc.id}>
              <button className={`card level-${inc.level} ${inc.active ? '' : 'inactive'}`} onClick={() => onSelect(inc.id)}>
                <div className="row">
                  <span className={`badge lvl ${inc.level}`}>{inc.level}</span>
                  <strong>{inc.zone_name}</strong>
                  <span className="quiet">{KIND_LABEL[inc.kind] || inc.kind}</span>
                  <span className="spacer" />
                  <span className="quiet">{inc.status !== 'open' ? STATUS_LABEL[inc.status] : inc.video_ts != null ? `▶ ${mmss(inc.video_ts)} in video` : ago(inc.started_at)}</span>
                </div>
                <div className="quiet small">{cameraName(inc.camera_id)}{inc.source_kind === 'upload' ? ' · recorded footage' : ''}</div>
                {inc.kind.startsWith('crowd') && inc.active && <CrushClock etaS={z?.eta_s} trend={z?.trend} />}
                <div className="chips">
                  {reasons.map((r) => <span key={r.signal} className="chip">{r.text} <b>+{r.points}</b></span>)}
                </div>
                {!inc.active && <div className="quiet small">{inc.source_kind === 'upload' ? 'Video moved on' : 'Cleared on camera'} · peak {inc.peak_level} · awaiting operator</div>}
              </button>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
