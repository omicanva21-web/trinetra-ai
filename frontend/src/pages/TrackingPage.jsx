import { useEffect, useMemo, useState } from 'react'
import { api, withToken } from '../api.js'
import { useCameraSender } from '../cameraSender.jsx'
import { SOURCE_LABEL, duration } from '../format.js'
import BrowserCameraPanel from '../components/BrowserCameraPanel.jsx'
import VideoPanel, { useVideoTimeline } from '../components/VideoPanel.jsx'
import TrackTable from '../components/TrackTable.jsx'
import TrajectoryMap from '../components/TrajectoryMap.jsx'
import ActivityFeed from '../components/ActivityFeed.jsx'
import { CrossingsChart, DwellHistogram, OccupancyChart } from '../components/Charts.jsx'
import { cameraBody } from '../components/ZoneEditor.jsx'

function initialCamera(cfg) {
  const fromHash = location.hash.replace('#', '').split('/')[1]
  const enabled = (cfg?.cameras || []).filter((c) => c.enabled)
  if (fromHash && enabled.some((c) => c.id === fromHash)) return fromHash
  const live = enabled.find((c) => ['webcam', 'browser'].includes(c.source_kind))
  return (live || enabled[0])?.id || ''
}

function Card({ title, sub, children, wide }) {
  return (
    <section className={`card-box ${wide ? 'wide' : ''}`}>
      <h3>{title}</h3>
      {sub && <p className="quiet small">{sub}</p>}
      {children}
    </section>
  )
}

export default function TrackingPage({ cfg, states, history, activity, epoch, setError, reloadConfig }) {
  const sender = useCameraSender()
  const [camId, setCamId] = useState(() => initialCamera(cfg))
  const [tracks, setTracks] = useState(null)
  const [tstats, setTstats] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (!camId && cfg) setCamId(initialCamera(cfg)) }, [cfg, camId])
  const camera = cfg?.cameras.find((c) => c.id === camId)
  const state = states[camId]
  const tr = state?.tracking
  const isUpload = camera?.source_kind === 'upload'
  const video = isUpload ? (state?.video || camera?.video) : null
  const timeline = useVideoTimeline(isUpload ? camId : null, video)

  useEffect(() => {
    if (!camId) return undefined
    const load = () => api.tracks(camId, 40).then(setTracks).catch(() => {})
    load()
    const id = setInterval(load, 3000)
    return () => clearInterval(id)
  }, [camId])
  useEffect(() => {
    if (!camId) return undefined
    const load = () => api.trackingStats(camId, 30).then(setTstats).catch(() => {})
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [camId])

  const session = video?.session
  // uploaded video: only this run's events (a restart starts a new run)
  const events = useMemo(() => activity.filter((e) => e.camera_id === camId && (!isUpload || e.session === session)),
    [activity, camId, isUpload, session])
  const totals = (tr?.lines || []).reduce((a, l) => ({ in: a.in + l.in, out: a.out + l.out }), { in: 0, out: 0 })

  const choose = (id) => { setCamId(id); location.hash = `tracking/${id}`; setTracks(null); setTstats(null) }
  const focus = async (tid) => {
    try { await api.focus(camId, tid) } catch (e) { setError(e.message) }
  }
  // Click a person in the video to follow them: nearest tracked feet to the click.
  const clickVideo = (e) => {
    if (!tr?.active?.length) return
    const r = e.currentTarget.getBoundingClientRect()
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height
    let best = null, bestD = 0.12
    for (const t of tr.active) {
      if (t.state === 'hidden') continue
      const d = Math.hypot(t.pos[0] - x, (t.pos[1] - y) * 0.6) // feet are below the click point on a body
      if (d < bestD) { best = t.id; bestD = d }
    }
    focus(best === tr.focus ? null : best)
  }
  const switchSource = async (source, deviceId = '') => {
    if (!camera) return
    setBusy(true)
    try {
      await api.updateCamera(camera.id, { ...cameraBody(camera), source })
      await reloadConfig()
      if (source === 'browser') setTimeout(() => sender.start(camera.id, deviceId, Math.min(15, camera.options?.max_fps || 15)), 800)
    } catch (e) { setError(e.message) }
    setBusy(false)
  }

  if (!cfg) return <main className="page"><p className="empty">Connecting to the backend…</p></main>
  if (!camera) return <main className="page"><p className="empty">No enabled cameras. Add one on the Setup page.</p></main>

  const status = state?.status || camera.status
  const counters = [
    ['Tracked now', tr?.active_count ?? '—'],
    ['Unique people', tr?.unique ?? '—'],
    ['Entered (IN)', totals.in],
    ['Left (OUT)', totals.out],
    ['Avg time in view', duration(tr?.avg_dwell_s)],
    ['Longest in view now', duration(tr?.longest_s)],
  ]

  return (
    <main className="page tracking">
      <div className="row toolbar-row">
        <h2>{isUpload ? 'Video tracking' : 'Live tracking'}</h2>
        <select value={camId} onChange={(e) => choose(e.target.value)} aria-label="Camera">
          {cfg.cameras.filter((c) => c.enabled).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <span className="badge sim">{SOURCE_LABEL[camera.source_kind] || camera.source_kind}</span>
        {!isUpload && status && status !== 'running' && <span className="badge warn">{status}</span>}
        <span className="quiet small">{state?.detector}</span>
        <span className="spacer" />
        {tr?.focus != null && <button className="btn" onClick={() => focus(null)}>Stop following #{tr.focus}</button>}
      </div>

      {isUpload
        ? <div className="card-box"><VideoPanel camera={camera} state={state} /></div>
        : <BrowserCameraPanel camera={camera} onSwitchSource={switchSource} busy={busy} />}

      <div className="tracking-grid">
        <section className="card-box video-box">
          {String(status || '').startsWith('error')
            ? <div className="novideo big"><b>No video</b><span>{String(status).replace(/^error: /, '')}</span></div>
            : <img className="live-video" src={withToken(`/stream/${camera.id}.mjpg?e=${epoch}`)} alt={`${isUpload ? 'Video' : 'Live'} tracking: ${camera.name}`} onClick={clickVideo}
                title="Click a person to follow them" />}
          <div className="counters">
            {counters.map(([label, value]) => (
              <div key={label} className="counter"><div className="kpi-label">{label}</div><div className="counter-value">{value}</div></div>
            ))}
          </div>
          <div className="row small quiet">
            <span>{state?.fps ? `${state.fps} frames/s analysed` : ''}</span>
            {(tr?.lines || []).map((l) => <span key={l.id}>· {l.name}: IN {l.in} / OUT {l.out}</span>)}
            <span className="spacer" />
            <span>Click a person in the video or a row in the table to follow them.</span>
          </div>
        </section>
        <aside className="card-box people-box">
          <h3>People in view <span className="count">{tr?.active_count ?? 0}</span></h3>
          <TrackTable rows={tr?.active || []} focusId={tr?.focus} onSelect={focus} />
        </aside>
      </div>

      <div className="grid">
        {isUpload ? (
          <Card title="People tracked through the video" sub="Time in the video (mm:ss). Solid: people with a tracking ID. Dashed: every detection.">
            <OccupancyChart samples={timeline?.session === session ? timeline?.samples || [] : []} video />
          </Card>
        ) : (
          <Card title="People tracked over time" sub="Solid: people with a tracking ID. Dashed: every detection, including unconfirmed ones.">
            <OccupancyChart samples={history[camId] || []} />
          </Card>
        )}
        <Card title={isUpload ? 'Entries and exits through the video' : 'Entries and exits per minute'}
          sub={`Counting lines, ${isUpload ? 'this run, by time in the video' : 'last 30 minutes'} · total IN ${tstats?.total_in ?? 0}, OUT ${tstats?.total_out ?? 0}`}>
          <CrossingsChart stats={tstats} />
        </Card>
        <Card title="Time in view" sub={`People who left ${isUpload ? 'the view in this run' : 'in the last 30 minutes'}: ${tstats?.people ?? 0} · average ${duration(tstats?.avg_dwell_s)} · median ${duration(tstats?.median_dwell_s)}`}>
          <DwellHistogram stats={tstats} />
        </Card>
        <Card title="Movement paths" sub={isUpload ? 'Where people walked in this run of the video' : 'Where people walked on this camera'} wide>
          <TrajectoryMap camera={camera} data={tracks} running={status === 'running' || (isUpload && !!video?.file)} />
        </Card>
        <Card title="Activity" sub={isUpload ? 'This run, newest first; times are positions in the video' : 'Live, newest first'}>
          <ActivityFeed events={events} />
        </Card>
        <Card title="Zone visits" sub={`People who entered each zone, ${isUpload ? 'this run' : 'last 30 minutes'}`}>
          {tstats && Object.keys(tstats.zone_visits || {}).length
            ? <table className="mini"><tbody>{Object.entries(tstats.zone_visits).map(([z, n]) => <tr key={z}><td>{z}</td><td>{n}</td></tr>)}</tbody></table>
            : <p className="empty">Shown once people who entered a zone have left the view.</p>}
        </Card>
      </div>
    </main>
  )
}
