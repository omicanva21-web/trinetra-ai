import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import KpiStrip from '../components/KpiStrip.jsx'
import { useVideoTimeline } from '../components/VideoPanel.jsx'
import { KindBars, LevelBars, PeopleChart, RiskBars, TimelineBars, VideoTimeChart, ZoneDensityChart } from '../components/Charts.jsx'
import { LEVEL_COLOR, SERIES, TREND_LABEL, VIDEO_STATE, duration, mmss } from '../format.js'

function Card({ title, sub, children, wide }) {
  return (
    <section className={`card-box ${wide ? 'wide' : ''}`}>
      <h3>{title}</h3>
      {sub && <p className="quiet small">{sub}</p>}
      {children}
    </section>
  )
}

// Incident numbers for the chosen source: live feeds only, or one uploaded video.
function useScopedStats(params) {
  const [stats, setStats] = useState(null)
  const key = JSON.stringify(params)
  useEffect(() => {
    let alive = true
    const load = () => api.stats(60, JSON.parse(key)).then((s) => { if (alive) setStats(s) }).catch(() => {})
    load()
    const id = setInterval(load, 5000)
    return () => { alive = false; clearInterval(id) }
  }, [key])
  return stats
}

function IncidentCards({ stats, note }) {
  return (
    <>
      <Card title="Alerts over the last hour" sub={`MEDIUM and HIGH incidents opened per ${stats?.bucket_min ?? 5}-minute block · ${note}`}>
        <TimelineBars stats={stats} />
      </Card>
      <Card title="Incidents by peak level" sub={`All incidents stored · ${note}`}>
        <LevelBars stats={stats} />
      </Card>
      <Card title="Incidents by type" sub={note}>
        <KindBars stats={stats} />
      </Card>
    </>
  )
}

function VideoAnalytics({ camera, state, profile }) {
  const video = state?.video || camera.video
  const timeline = useVideoTimeline(camera.id, video)
  const [tstats, setTstats] = useState(null)
  const stats = useScopedStats({ scope: 'video', camera_id: camera.id, ...(video?.video_id ? { video_id: video.video_id } : {}) })
  useEffect(() => {
    let alive = true
    const load = () => api.trackingStats(camera.id, 30).then((s) => { if (alive) setTstats(s) }).catch(() => {})
    load()
    const id = setInterval(load, 4000)
    return () => { alive = false; clearInterval(id) }
  }, [camera.id])

  if (!video?.file) {
    return <Card title={camera.name} wide><p className="empty">No video uploaded yet. Upload one on the Camera 4 card (Live page) or the Tracking page, press Start processing, and its analysis appears here.</p></Card>
  }
  const samples = timeline?.session && timeline.session === video.session ? timeline.samples : []
  const last = samples.at(-1)
  const fpsAvg = samples.length ? samples.reduce((n, s) => n + (s.fps || 0), 0) / samples.filter((s) => s.fps).length || 0 : 0
  const zones = (camera.zones || []).filter((z) => z.polygon_norm)
  const densityZones = zones.filter((z) => samples.some((s) => s.zones?.[z.id]?.density != null))
  const tr = state?.tracking

  return (
    <>
      <Card title={`${camera.name}: ${video.file}`} sub="Recorded footage, analysed by the same detector and tracker as the live cameras. Times are positions in the video (mm:ss), not clock times." wide>
        <div className="table-wrap">
          <table className="mini">
            <tbody>
              <tr><td>Status</td><td><span className={`badge vstate vs-${video.state}`}>{VIDEO_STATE[video.state]}</span> · processed {mmss(video.position_s)} of {mmss(video.duration_s)}{video.progress != null ? ` (${Math.round(video.progress * 100)}%)` : ''}</td></tr>
              <tr><td>Video</td><td>{video.width}×{video.height} · {video.video_fps ?? '—'} fps · {video.container?.toUpperCase()} {video.codec}</td></tr>
              <tr><td>Processing rate</td><td>{fpsAvg ? `${fpsAvg.toFixed(1)} frames analysed per second (average)` : '—'} · {video.frames_analysed} frames analysed</td></tr>
              <tr><td>People tracked (unique, this run)</td><td><b>{tr?.unique ?? last?.unique ?? 0}</b> · not matched across cameras or videos</td></tr>
              <tr><td>Counting lines</td><td>{(tr?.lines || []).map((l) => `${l.name}: IN ${l.in} · OUT ${l.out}`).join(' — ') || '—'}</td></tr>
              <tr><td>Time in view (people who left)</td><td>{tstats?.people ?? 0} people · average {duration(tstats?.avg_dwell_s)} · longest {duration(tstats?.longest_s)}</td></tr>
              <tr><td>Incidents from this video</td><td>{stats ? `${stats.total} (HIGH ${stats.by_level.HIGH}, MEDIUM ${stats.by_level.MEDIUM})` : '—'}</td></tr>
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="People detected through the video" sub="Solid: people with a tracking ID. Dashed: every person detection in the frame.">
        <VideoTimeChart samples={samples} series={[{ key: 'tracked', name: 'Tracked people', step: true }, { key: 'people', name: 'Detections', color: '#8b98a8', dash: '4 3', step: true }]} />
      </Card>
      <Card title="Unique people tracked" sub="Running total of distinct tracking IDs seen for at least 1 s">
        <VideoTimeChart samples={samples} series={[{ key: 'unique', name: 'Unique people', step: true, color: SERIES[2] }]} />
      </Card>
      <Card title="Processing rate" sub={`Frames analysed per second of processing; the video was recorded at ${video.video_fps ?? '?'} fps`}>
        <VideoTimeChart samples={samples} unit=" fps" series={[{ key: 'fps', name: 'Analysed fps', color: SERIES[3] }]}
          refY={video.video_fps ? { y: video.video_fps, label: `video ${video.video_fps} fps` } : undefined} />
      </Card>
      <Card title="Entries and exits" sub="Running totals on the counting lines">
        <VideoTimeChart samples={samples} series={[{ key: 'in', name: 'IN', step: true, color: '#56d4dd' }, { key: 'out', name: 'OUT', step: true, color: '#d2a8ff' }]} />
      </Card>
      {zones.length > 0 && (
        <Card title="People in each zone" sub={zones.map((z) => z.name).join(', ')}>
          <VideoTimeChart samples={samples} series={zones.map((z, i) => ({ key: (s) => s.zones?.[z.id]?.count ?? null, name: z.name, step: true, color: SERIES[(i + 4) % SERIES.length] }))} />
        </Card>
      )}
      {densityZones.map((z) => (
        <Card key={z.id} title={`${z.name} density`} sub="People per m², from the zone's floor size">
          <VideoTimeChart samples={samples} unit="/m²" series={[{ key: (s) => s.zones?.[z.id]?.density ?? null, name: 'Density' }]}
            refY={profile?.thresholds ? { y: profile.thresholds.density_danger, label: `danger ${profile.thresholds.density_danger}` } : undefined} />
        </Card>
      ))}
      {!densityZones.length && (
        <Card title="Crowd density">
          <p className="quiet small">Density needs the floor size of a zone. On the Setup page, edit Camera 4 and enter the gathering area's size in m² (or calibrate the floor); until then zones report people counts only, and no density alerts are raised.</p>
        </Card>
      )}
      <IncidentCards stats={stats} note="this video only" />
    </>
  )
}

export default function AnalyticsPage({ cfg, states, history, profile, stats, queue }) {
  const enabled = useMemo(() => (cfg ? cfg.cameras.filter((c) => c.enabled) : []), [cfg])
  const cameras = useMemo(() => enabled.filter((c) => c.source_kind !== 'upload'), [enabled])
  const videoCams = enabled.filter((c) => c.source_kind === 'upload')
  const [source, setSource] = useState('live')
  const videoCam = videoCams.find((c) => c.id === source)
  const liveStats = useScopedStats({ scope: 'live' })
  const crowdZones = cameras.flatMap((c) => (c.zones || []).filter((z) => z.kind === 'crowd').map((z) => ({ cam: c, zone: z })))

  return (
    <main className="page">
      <KpiStrip states={states} stats={stats} queue={queue} cfg={cfg} />
      {videoCams.length > 0 && (
        <div className="row toolbar-row">
          <label className="row source-filter">Source
            <select value={videoCam ? source : 'live'} onChange={(e) => setSource(e.target.value)} aria-label="Analytics source">
              <option value="live">Live, simulated and sample-clip cameras</option>
              {videoCams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <span className="quiet small">{videoCam ? 'Recorded footage: kept separate from live totals.' : 'Uploaded videos are not mixed into these numbers; choose one above.'}</span>
        </div>
      )}
      <div className="grid">
        {videoCam ? <VideoAnalytics camera={videoCam} state={states[videoCam.id]} profile={profile} /> : (
          <>
            <Card title="People in view" sub="Per camera, last 30 minutes, one point every 2 s" wide>
              <PeopleChart history={history} cameras={cameras} />
            </Card>

            <Card title="Live risk by zone" sub="0–100; amber line = MEDIUM (35), red line = HIGH (70)" wide>
              <RiskBars states={states} cameras={cameras} />
            </Card>

            {crowdZones.map(({ cam, zone }) => {
              const z = states[cam.id]?.zones?.find((x) => x.id === zone.id)
              return (
                <Card key={`${cam.id}:${zone.id}`} title={`${zone.name} density`} sub={cam.name}>
                  <div className="row small">
                    <span>Now <b>{z?.density != null ? `${z.density.toFixed(2)}/m²` : '—'}</b></span>
                    <span>Trend <b>{TREND_LABEL[z?.trend] || '—'}</b></span>
                    <span>Crush Clock <b style={{ color: z?.eta_s != null ? LEVEL_COLOR.MEDIUM : undefined }}>
                      {z?.trend === 'critical' ? 'at danger' : z?.eta_s != null ? duration(z.eta_s) : '—'}</b></span>
                  </div>
                  <ZoneDensityChart samples={history[cam.id] || []} zoneId={zone.id} thresholds={profile.thresholds} />
                </Card>
              )
            })}

            <IncidentCards stats={videoCams.length ? liveStats : stats} note={videoCams.length ? 'live and simulated cameras' : 'all cameras'} />
            <Card title="Response performance">
              <table className="mini">
                <tbody>
                  <tr><td>Incidents stored</td><td>{stats?.total ?? '—'}</td></tr>
                  <tr><td>Still open</td><td>{stats?.open ?? '—'}</td></tr>
                  <tr><td>Average time to first action</td><td>{duration(stats?.avg_response_s)}</td></tr>
                  <tr><td>Average time to close</td><td>{duration(stats?.avg_resolve_s)}</td></tr>
                  <tr><td>False-alarm rate</td><td>{stats?.false_alarm_rate == null ? '—' : `${Math.round(stats.false_alarm_rate * 100)}%`}</td></tr>
                  <tr><td>Vehicles in view now</td><td>{stats?.live?.vehicles ?? '—'}</td></tr>
                </tbody>
              </table>
              {videoCams.length > 0 && <p className="quiet small">Response numbers cover every incident, including ones from uploaded videos.</p>}
            </Card>
          </>
        )}
      </div>
    </main>
  )
}
