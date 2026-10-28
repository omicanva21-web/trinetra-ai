import { useEffect, useState } from 'react'
import { api, readToken, saveToken } from '../api.js'
import ZoneEditor, { cameraBody } from '../components/ZoneEditor.jsx'

const SOURCE_TYPES = [
  ['webcam', 'Webcam (opened directly)', '0'],
  ['browser', 'Browser camera (opened by this page)', 'browser'],
  ['file', 'Video file', 'clips/my_clip.mp4'],
  ['rtsp', 'IP camera (RTSP/HTTP)', 'rtsp://user:password@192.168.1.20:554/stream1'],
  ['mock', 'Simulated crowd', 'mock'],
  ['upload', 'Uploaded video (upload it from the dashboard)', 'upload'],
]
const PROFILE_FIELDS = [
  ['density_warn', 'Density warn (people/m²)', 0.1], ['density_danger', 'Density danger (people/m²)', 0.1],
  ['eta_alert_s', 'Crush Clock alert window (s)', 1], ['speed_surge_mps', 'Surge speed (m/s)', 0.1],
  ['dwell_limit_s', 'Default dwell limit (s)', 1], ['pressure_ref', 'Crowd pressure reference (1/s²)', 0.005],
]

function AddCamera({ onAdded, onError }) {
  const [type, setType] = useState('webcam')
  const [name, setName] = useState('New camera')
  const [source, setSource] = useState('0')
  const [busy, setBusy] = useState(false)
  const pick = (t) => { setType(t); setSource(SOURCE_TYPES.find(([k]) => k === t)[2]) }
  const add = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      const cam = await api.addCamera({
        name, source, enabled: true,
        options: { max_fps: ['webcam', 'browser', 'upload'].includes(type) ? 15 : 8, model: 'fast', heatmap: false, trails: true },
        // an uploaded video's floor size is unknown: count people only until you enter it
        zones: [{ name: 'Whole view', kind: 'crowd', ...(type === 'upload' ? {} : { area_m2: 10 }), polygon_norm: [[0, 0], [1, 0], [1, 1], [0, 1]] }],
        lines: [{ name: 'Counting line', points_norm: [[0.5, 1], [0.5, 0]] }],
      })
      onAdded(cam)
    } catch (err) { onError(err.message) }
    setBusy(false)
  }
  return (
    <form className="card-box" onSubmit={add}>
      <h3>Add a camera</h3>
      <div className="form-grid">
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} required /></label>
        <label>Type
          <select value={type} onChange={(e) => pick(e.target.value)}>
            {SOURCE_TYPES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </label>
        <label>Source<input value={source} onChange={(e) => setSource(e.target.value)} maxLength={500} required /></label>
      </div>
      <p className="quiet small">A new camera starts with one crowd zone covering the whole view (10 m²; no size for an uploaded video) and a vertical counting line down the middle. Draw your own after adding it. A browser camera is started from the Tracking page; an uploaded-video camera gets its video from its card on the Live page.</p>
      <button className="btn primary" disabled={busy}>{busy ? 'Adding…' : 'Add camera'}</button>
    </form>
  )
}

function Thresholds({ onError }) {
  const [data, setData] = useState(null)
  const [name, setName] = useState('')
  const [form, setForm] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    api.profiles().then((d) => { setData(d); setName(d.current); setForm(d.profiles[d.current]) }).catch((e) => onError(e.message))
  }, [onError])
  if (!data || !form) return null
  const choose = (n) => { setName(n); setForm(data.profiles[n]); setMsg('') }
  const save = async () => {
    try {
      const body = { ...form, ...Object.fromEntries(PROFILE_FIELDS.map(([k]) => [k, Number(form[k])])) }
      const out = await api.updateProfile(name, body)
      setData((d) => ({ ...d, profiles: { ...d.profiles, [name]: out } }))
      setMsg(name === data.current ? 'Saved and applied live.' : 'Saved. Switch to this profile in the header to use it.')
    } catch (e) { onError(e.message) }
  }
  return (
    <section className="card-box">
      <h3>Alert thresholds</h3>
      <div className="row">
        <label>Profile
          <select value={name} onChange={(e) => choose(e.target.value)}>
            {Object.keys(data.profiles).map((k) => <option key={k} value={k}>{k}{k === data.current ? ' (in use)' : ''}</option>)}
          </select>
        </label>
        <label className="grow">Label<input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} maxLength={80} /></label>
      </div>
      <div className="form-grid">
        {PROFILE_FIELDS.map(([k, label, step]) => (
          <label key={k}>{label}<input type="number" step={step} min="0" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>
        ))}
      </div>
      <p className="quiet small">Station profile follows crowd-safety guidance (bodies touch at about 5/m²). Use the demo profile only for safe staged demos, and say so.</p>
      <div className="row"><button className="btn primary" onClick={save}>Save thresholds</button>{msg && <span className="ok-text">{msg}</span>}</div>
    </section>
  )
}

export default function SetupPage({ cfg, states, setError, reloadConfig }) {
  const [cams, setCams] = useState([])
  const [editId, setEditId] = useState(null)
  const [token, setToken] = useState(readToken())

  const load = () => api.cameras().then(setCams).catch((e) => setError(e.message))
  useEffect(() => {
    load()
    const id = setInterval(load, 3000)
    return () => clearInterval(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = async (cam) => {
    try { await api.updateCamera(cam.id, { ...cameraBody(cam), enabled: !cam.enabled }); load(); reloadConfig() } catch (e) { setError(e.message) }
  }
  const remove = async (cam) => {
    if (!window.confirm(`Delete camera “${cam.name}”? Its incidents and tracking history stay.`)) return
    try { await api.deleteCamera(cam.id); if (editId === cam.id) setEditId(null); load(); reloadConfig() } catch (e) { setError(e.message) }
  }
  const editing = cams.find((c) => c.id === editId)

  return (
    <main className="page setup">
      {cfg?.auth_required && (
        <section className="card-box">
          <h3>Operator token</h3>
          <div className="row">
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="OPERATOR_TOKEN from .env" />
            <button className="btn primary" onClick={() => { saveToken(token); location.reload() }}>Save and reload</button>
          </div>
        </section>
      )}

      <section className="card-box">
        <h3>Cameras</h3>
        <div className="table-wrap">
          <table className="incidents">
            <thead><tr><th>Name</th><th>Source</th><th>Status</th><th>Detector</th><th>FPS</th><th>People</th><th>Enabled</th><th /></tr></thead>
            <tbody>
              {cams.map((c) => (
                <tr key={c.id} className={editId === c.id ? 'sel' : ''}>
                  <td>{c.name}</td>
                  <td><code>{String(c.source)}</code> <span className="quiet small">{c.source_kind === 'upload' ? 'uploaded video' : c.source_kind}</span>
                    {c.source_kind === 'upload' && c.video?.file && <div className="quiet small">{c.video.file}</div>}</td>
                  <td><span className={`badge ${c.status === 'running' ? 'lvl LOW' : c.status === 'disabled' ? 'sim' : 'warn'}`}>{c.status}</span></td>
                  <td className="small">{c.detector || '—'}</td>
                  <td>{c.fps || '—'}</td>
                  <td>{states[c.id]?.people ?? '—'}</td>
                  <td><input type="checkbox" aria-label={`Enable ${c.name}`} checked={c.enabled} onChange={() => toggle(c)} /></td>
                  <td className="nowrap">
                    <button className="btn" onClick={() => setEditId(c.id)}>Edit zones</button>{' '}
                    <button className="btn danger" onClick={() => remove(c)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {editing && (
        <section className="card-box">
          <div className="row"><h3>Edit: {editing.name}</h3><span className="spacer" /><button className="link" onClick={() => setEditId(null)}>Close</button></div>
          {editing.source_kind === 'upload' && (
            <p className="note small">
              {editing.video?.file
                ? <>Zones are drawn on a frame of “{editing.video.file}”. Saving restarts this camera: if the video is being processed, it stops; press Start processing again. To get density alerts, enter the gathering area's real size in m².</>
                : <>Upload a video on this camera's card first, then draw zones on its first frame.</>}
            </p>
          )}
          <ZoneEditor camera={editing} onError={setError} onSaved={() => { load(); reloadConfig() }} />
        </section>
      )}

      <AddCamera onError={setError} onAdded={(cam) => { load(); reloadConfig(); setEditId(cam.id) }} />
      <Thresholds onError={setError} />
    </main>
  )
}
