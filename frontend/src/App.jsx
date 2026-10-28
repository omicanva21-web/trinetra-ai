import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { useLiveSocket } from './useLiveSocket.js'
import { CameraSenderProvider, useCameraSender } from './cameraSender.jsx'
import { CLOSED, RANK } from './format.js'
import LivePage from './pages/LivePage.jsx'
import TrackingPage from './pages/TrackingPage.jsx'
import AnalyticsPage from './pages/AnalyticsPage.jsx'
import IncidentsPage from './pages/IncidentsPage.jsx'
import SetupPage from './pages/SetupPage.jsx'

const TABS = [['live', 'Live'], ['tracking', 'Tracking'], ['analytics', 'Analytics'], ['incidents', 'Incidents'], ['setup', 'Setup']]
const HISTORY_MAX = 1800 // 30 minutes at one sample per second

function pageFromHash() {
  const h = (typeof location !== 'undefined' ? location.hash : '').replace('#', '').split('/')[0]
  return TABS.some(([k]) => k === h) ? h : 'live'
}

// The same sample shape the server keeps in /api/metrics, built from live state messages.
function sampleOf(state) {
  const tr = state.tracking || {}
  return {
    ts: state.ts || Date.now() / 1000, people: state.people, vehicles: state.vehicles, score: state.score,
    tracked: tr.active_count || 0, unique: tr.unique || 0,
    lines: Object.fromEntries((tr.lines || []).map((l) => [l.id, [l.in, l.out]])),
    zones: Object.fromEntries(state.zones.map((z) => [z.id, { count: z.count, density: z.density, score: z.score, eta_s: z.eta_s, level: z.level }])),
  }
}

function StreamingChip() {
  const sender = useCameraSender()
  if (!sender.running && !sender.starting) return null
  return <div className="conn ok" title={sender.label}>● Camera streaming {sender.running ? `${sender.sentFps} fps` : '…'}</div>
}

function Dashboard() {
  const [page, setPage] = useState(pageFromHash)
  const [cfg, setCfg] = useState(null)
  const [states, setStates] = useState({})
  const [incidents, setIncidents] = useState({})
  const [history, setHistory] = useState({})
  const [activity, setActivity] = useState([])
  const [profile, setProfile] = useState({ name: '', thresholds: null })
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')
  const [epoch, setEpoch] = useState(0) // +1 on every (re)connect: video streams re-open after a server restart

  const loadConfig = useCallback(() => api.config()
    .then((c) => { setCfg(c); setProfile({ name: c.profile, thresholds: c.thresholds }) })
    .catch((e) => setError(`Backend not reachable: ${e.message}`)), [])

  useEffect(() => { loadConfig() }, [loadConfig])
  useEffect(() => { api.metrics(30).then(setHistory).catch(() => {}) }, [])
  useEffect(() => {
    const load = () => api.stats().then(setStats).catch(() => {})
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])
  useEffect(() => {
    const onHash = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const connected = useLiveSocket((msg) => {
    if (msg.type === 'hello') {
      setEpoch((e) => e + 1)
      setStates(Object.fromEntries(msg.states.map((s) => [s.camera_id, s])))
      setIncidents((m) => ({ ...m, ...Object.fromEntries(msg.incidents.map((i) => [i.id, i])) }))
      if (msg.thresholds) setProfile({ name: msg.profile, thresholds: msg.thresholds })
    } else if (msg.type === 'state') {
      setStates((s) => ({ ...s, [msg.camera_id]: msg }))
      setHistory((h) => {
        const list = h[msg.camera_id] || []
        const sample = sampleOf(msg)
        if (list.length && sample.ts - list.at(-1).ts < 1) return h
        return { ...h, [msg.camera_id]: [...list.slice(-(HISTORY_MAX - 1)), sample] }
      })
    } else if (msg.type === 'incident') {
      setIncidents((m) => ({ ...m, [msg.incident.id]: msg.incident }))
    } else if (msg.type === 'track_event') {
      setActivity((a) => [{ ...msg, at: Date.now() / 1000 }, ...a].slice(0, 80))
    } else if (msg.type === 'camera_status') {
      setStates((s) => ({ ...s, [msg.camera_id]: { zones: [], people: 0, ...s[msg.camera_id], status: msg.status } }))
    } else if (msg.type === 'profile') {
      setProfile({ name: msg.profile, thresholds: msg.thresholds })
    } else if (msg.type === 'config_changed') {
      loadConfig()
    }
  })

  const queue = useMemo(
    () => Object.values(incidents)
      .filter((i) => !CLOSED.has(i.status))
      .sort((a, b) => (b.active - a.active) || (RANK[b.level] - RANK[a.level]) || (b.score - a.score) || (b.started_at - a.started_at)),
    [incidents],
  )

  const go = (p) => { location.hash = p; setPage(p) }
  const switchProfile = async (name) => {
    try { await api.setProfile(name) } catch (e) { setError(e.message) }
  }
  const shared = { cfg, states, incidents, history, activity, profile, stats, queue, epoch, setError, setIncidents, reloadConfig: loadConfig }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">TRINETRA <span>AI</span></div>
        <nav className="tabs" aria-label="Pages">
          {TABS.map(([key, label]) => (
            <button key={key} className={page === key ? 'active' : ''} onClick={() => go(key)}>
              {label}{key === 'live' && queue.length ? <span className="pill">{queue.length}</span> : null}
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <StreamingChip />
        {cfg && (
          <select value={profile.name} onChange={(e) => switchProfile(e.target.value)} aria-label="Threshold profile">
            {Object.entries(cfg.profiles).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        )}
        <div className={`conn ${connected ? 'ok' : 'down'}`}>{connected ? 'Live' : 'Reconnecting…'}</div>
      </header>

      {error && <div className="banner" role="alert" onClick={() => setError('')}>{error} <span className="quiet">(click to dismiss)</span></div>}

      {page === 'live' && <LivePage {...shared} />}
      {page === 'tracking' && <TrackingPage {...shared} />}
      {page === 'analytics' && <AnalyticsPage {...shared} />}
      {page === 'incidents' && <IncidentsPage {...shared} />}
      {page === 'setup' && <SetupPage {...shared} />}
    </div>
  )
}

export default function App() {
  return (
    <CameraSenderProvider>
      <Dashboard />
    </CameraSenderProvider>
  )
}
