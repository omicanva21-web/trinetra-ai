import { duration, trackColor } from '../format.js'

const STATE_LABEL = { moving: 'moving', still: 'still', hidden: 'hidden' }

export default function TrackTable({ rows, focusId, onSelect }) {
  const sorted = [...rows].sort((a, b) => (a.state === 'hidden') - (b.state === 'hidden') || b.age_s - a.age_s)
  if (!sorted.length) return <p className="empty">Nobody in view. Walk in front of the camera.</p>
  return (
    <div className="table-wrap">
      <table className="incidents tracks">
        <thead>
          <tr><th>ID</th><th>In view</th><th>Zone</th><th>Speed</th><th>Walked</th><th>State</th></tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.id} className={`${focusId === r.id ? 'sel' : ''} ${r.state === 'hidden' ? 'dimmed' : ''}`}
              onClick={() => onSelect(focusId === r.id ? null : r.id)} tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && onSelect(focusId === r.id ? null : r.id)}
              title={focusId === r.id ? 'Click to stop highlighting' : 'Click to highlight on the video'}>
              <td className="nowrap"><span className="swatch" style={{ background: trackColor(r.id) }} /> #{r.id}{r.cls === 'vehicle' ? ' 🚗' : ''}</td>
              <td>{duration(r.age_s)}</td>
              <td>{r.zones.length
                ? r.zones.map((z) => <span key={z.name} className={`zchip ${z.kind}`}>{z.name} · {duration(z.s)}</span>)
                : <span className="quiet">—</span>}</td>
              <td className="nowrap">{r.speed == null ? '—' : `${r.est ? '≈' : ''}${r.speed.toFixed(1)} m/s`}</td>
              <td className="nowrap">{r.dist == null ? '—' : `${r.est ? '≈' : ''}${r.dist.toFixed(1)} m`}</td>
              <td><span className={`state ${r.state}`}>{STATE_LABEL[r.state] || r.state}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
