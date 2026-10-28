import { useMemo, useState } from 'react'
import KpiStrip from '../components/KpiStrip.jsx'
import CameraTile from '../components/CameraTile.jsx'
import AlertQueue from '../components/AlertQueue.jsx'
import IncidentPanel from '../components/IncidentPanel.jsx'

export default function LivePage({ cfg, states, incidents, history, profile, stats, queue, epoch, setError, setIncidents }) {
  const [selectedId, setSelectedId] = useState(null)
  const cameras = useMemo(() => {
    const list = cfg ? cfg.cameras.filter((c) => c.enabled) : []
    // riskiest feed first; uploaded-video cards stay at the end so their controls do not jump around
    const rank = (c) => (c.source_kind === 'upload' ? -1 : states[c.id]?.score || 0)
    return [...list].sort((a, b) => rank(b) - rank(a))
  }, [cfg, states])
  const liveZone = (inc) => states[inc.camera_id]?.zones?.find((z) => z.id === inc.zone_id)
  const cameraName = (id) => cfg?.cameras.find((c) => c.id === id)?.name || id
  const selected = selectedId ? incidents[selectedId] : null

  return (
    <main className="page">
      <KpiStrip states={states} stats={stats} queue={queue} cfg={cfg} />
      <div className="layout">
        <section className="wall" aria-label="Camera wall">
          {cameras.map((c) => <CameraTile key={c.id} camera={c} state={states[c.id]} epoch={epoch} onOpen={() => { location.hash = `tracking/${c.id}` }} />)}
          {cfg && !cameras.length && <div className="empty">No cameras enabled. Add one on the Setup page.</div>}
          {!cfg && <div className="empty">Connecting to the backend…</div>}
        </section>
        <aside className="side">
          {selected ? (
            <IncidentPanel
              incident={selected}
              zone={liveZone(selected)}
              samples={history[selected.camera_id] || []}
              thresholds={profile.thresholds}
              cameraName={cameraName}
              onClose={() => setSelectedId(null)}
              onError={setError}
              onChanged={(row) => setIncidents((m) => ({ ...m, [row.id]: row }))}
            />
          ) : (
            <AlertQueue incidents={queue} liveZone={liveZone} onSelect={setSelectedId} cameraName={cameraName} />
          )}
        </aside>
      </div>
    </main>
  )
}
