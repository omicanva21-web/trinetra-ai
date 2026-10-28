import { useEffect, useState } from 'react'
import { api } from '../api.js'
import IncidentPanel from '../components/IncidentPanel.jsx'
import { KIND_LABEL, STATUS_LABEL, clock, duration, mmss } from '../format.js'

function toCsv(rows, cameraName) {
  const head = ['id', 'started', 'camera', 'zone', 'type', 'peak_level', 'status', 'duration_s', 'source', 'video_file', 'video_time']
  const lines = rows.map((r) => [r.id, new Date(r.started_at * 1000).toISOString(), cameraName(r.camera_id), r.zone_name,
    KIND_LABEL[r.kind] || r.kind, r.peak_level, r.status,
    Math.round(r.video_ts != null && r.video_end != null ? r.video_end - r.video_ts : r.updated_at - r.started_at),
    r.source_kind === 'upload' ? 'uploaded video' : 'camera', r.video_name || '', r.video_ts != null ? mmss(r.video_ts) : '']
    .map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','))
  return [head.join(','), ...lines].join('\n')
}

export default function IncidentsPage({ cfg, states, incidents, history, profile, setError, setIncidents }) {
  const [filters, setFilters] = useState({ status: '', level: '', camera_id: '' })
  const [rows, setRows] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const cameraName = (id) => cfg?.cameras.find((c) => c.id === id)?.name || id

  useEffect(() => {
    const load = () => api.incidents({ ...filters, limit: 500 }).then(setRows).catch((e) => setError(e.message))
    load()
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [filters, setError])

  const merged = rows.map((r) => incidents[r.id] || r)
  const selected = selectedId ? (incidents[selectedId] || rows.find((r) => r.id === selectedId)) : null
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }))
  const exportCsv = () => {
    const blob = new Blob([toCsv(merged, cameraName)], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `trinetra-incidents-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <main className="page">
      <div className="layout">
        <section className="card-box">
          <div className="row">
            <h2>Incident history <span className="count">{merged.length}</span></h2>
            <span className="spacer" />
            <select value={filters.status} onChange={set('status')} aria-label="Status filter">
              <option value="">All statuses</option>
              <option value="open">Open (any)</option>
              {Object.entries(STATUS_LABEL).filter(([k]) => k !== 'open').map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select value={filters.level} onChange={set('level')} aria-label="Level filter">
              <option value="">All levels</option><option value="HIGH">HIGH</option><option value="MEDIUM">MEDIUM</option>
            </select>
            <select value={filters.camera_id} onChange={set('camera_id')} aria-label="Camera filter">
              <option value="">All cameras</option>
              {(cfg?.cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button className="btn" onClick={exportCsv} disabled={!merged.length}>Export CSV</button>
          </div>
          <div className="table-wrap">
            <table className="incidents">
              <thead>
                <tr><th>Started</th><th>Camera</th><th>Zone</th><th>Type</th><th>Peak</th><th>Status</th><th>Duration</th><th>Evidence</th></tr>
              </thead>
              <tbody>
                {merged.map((r) => (
                  <tr key={r.id} className={selectedId === r.id ? 'sel' : ''} onClick={() => setSelectedId(r.id)} tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && setSelectedId(r.id)}>
                    <td>
                      {r.video_ts != null
                        ? <><b title="Position in the uploaded video">▶ {mmss(r.video_ts)}</b> <span className="quiet small">in video · processed {clock(r.started_at)}</span></>
                        : clock(r.started_at)}
                    </td>
                    <td>{cameraName(r.camera_id)}{r.source_kind === 'upload' && <div className="quiet small">Uploaded video{r.video_name ? `: ${r.video_name}` : ''}</div>}</td>
                    <td>{r.zone_name}</td>
                    <td>{KIND_LABEL[r.kind] || r.kind}</td>
                    <td><span className={`badge lvl ${r.peak_level}`}>{r.peak_level}</span></td>
                    <td>{STATUS_LABEL[r.status]}{r.active ? ' · live' : ''}</td>
                    <td>{r.video_ts != null && r.video_end != null
                      ? <span title="On the video's own clock">{duration(r.video_end - r.video_ts)}</span>
                      : duration(r.updated_at - r.started_at)}</td>
                    <td>{r.has_snapshot ? 'photo' : ''}{r.has_clip ? ' + clip' : ''}</td>
                  </tr>
                ))}
                {!merged.length && <tr><td colSpan={8} className="empty">No incidents match these filters yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
        <aside className="side">
          {selected ? (
            <IncidentPanel
              incident={selected}
              zone={states[selected.camera_id]?.zones?.find((z) => z.id === selected.zone_id)}
              samples={history[selected.camera_id] || []}
              thresholds={profile.thresholds}
              cameraName={cameraName}
              onClose={() => setSelectedId(null)}
              onError={setError}
              onChanged={(row) => setIncidents((m) => ({ ...m, [row.id]: row }))}
            />
          ) : <p className="empty">Select an incident to see its evidence and log.</p>}
        </aside>
      </div>
    </main>
  )
}
