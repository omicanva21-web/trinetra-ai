import { SOURCE_GROUP, duration } from '../format.js'

const GROUP_LABEL = { live: 'live', simulated: 'simulated', clip: 'sample clip', upload: 'uploaded video' }

export default function KpiStrip({ states, stats, queue, cfg }) {
  const enabled = cfg ? cfg.cameras.filter((c) => c.enabled) : []
  const isUpload = (id) => enabled.find((c) => c.id === id)?.source_kind === 'upload'
  // "Now" totals come from live, simulated and sample-clip feeds; an uploaded recording is not happening now
  const live = Object.values(states).filter((s) => enabled.some((c) => c.id === s.camera_id) && !isUpload(s.camera_id))
  const people = live.reduce((n, s) => n + (s.people || 0), 0)
  const unique = live.reduce((n, s) => n + (s.tracking?.unique || 0), 0)
  const running = Object.values(states).filter((s) => s.status === 'running' && enabled.some((c) => c.id === s.camera_id)).length
  const total = enabled.length
  const groups = enabled.reduce((m, c) => { const g = SOURCE_GROUP[c.source_kind] || 'live'; m[g] = (m[g] || 0) + 1; return m }, {})
  const mix = Object.entries(groups).map(([g, n]) => `${n} ${GROUP_LABEL[g]}`).join(' · ')
  const high = queue.filter((i) => i.level === 'HIGH' && i.active).length
  const videos = enabled.filter((c) => c.source_kind === 'upload').length
  const tiles = [
    ['People in view', people, `across ${live.length} camera${live.length === 1 ? '' : 's'}${videos ? ' (uploaded video not included)' : ''}`],
    ['Unique people', unique, `tracked since start${videos ? ', live feeds only' : ''}`],
    ['Cameras running', `${running}/${total}`, mix || 'with live analysis'],
    ['Open incidents', queue.length, `${high} HIGH right now`],
    ['Avg response', duration(stats?.avg_response_s), `${stats?.responded ?? 0} incidents answered`],
  ]
  return (
    <section className="kpis" aria-label="Key numbers">
      {tiles.map(([label, value, sub]) => (
        <div key={label} className={`kpi ${label === 'Open incidents' && high ? 'alert' : ''}`}>
          <div className="kpi-label">{label}</div>
          <div className="kpi-value">{value}</div>
          <div className="kpi-sub">{sub}</div>
        </div>
      ))}
    </section>
  )
}
