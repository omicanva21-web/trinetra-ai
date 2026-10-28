import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { SERIES } from '../format.js'

const r4 = (v) => Math.round(Math.min(1, Math.max(0, v)) * 10000) / 10000
const DEFAULT_OPTIONS = { max_fps: 10, model: 'fast', heatmap: true, trails: true }

export function cameraBody(cam) {
  return {
    name: cam.name,
    source: String(cam.source),
    enabled: cam.enabled !== false,
    zones: (cam.zones || []).filter((z) => z.polygon_norm).map((z) => ({
      id: z.id, name: z.name, kind: z.kind, polygon_norm: z.polygon_norm,
      ...(z.area_m2 ? { area_m2: Number(z.area_m2) } : {}),
      ...(z.kind === 'restricted' && z.base_score !== undefined && z.base_score !== '' ? { base_score: Number(z.base_score) } : {}),
      ...(z.kind === 'restricted' && z.dwell_limit_s ? { dwell_limit_s: Number(z.dwell_limit_s) } : {}),
      ...(z.classes ? { classes: z.classes } : {}),
    })),
    lines: (cam.lines || []).map((l) => ({ id: l.id, name: l.name, points_norm: l.points_norm })),
    options: { ...DEFAULT_OPTIONS, ...(cam.options || {}), max_fps: Number(cam.options?.max_fps ?? DEFAULT_OPTIONS.max_fps) },
    calibration: cam.calibration?.image_points_norm
      ? { image_points_norm: cam.calibration.image_points_norm, width_m: Number(cam.calibration.width_m), length_m: Number(cam.calibration.length_m) }
      : null,
  }
}

// Arrow from the middle of a counting line towards its IN side, computed in pixels so it looks right.
function inArrow([[ax, ay], [bx, by]], [W, H]) {
  const dx = (bx - ax) * W, dy = (by - ay) * H
  const len = Math.hypot(dx, dy) || 1
  const nx = -dy / len, ny = dx / len
  const mx = ((ax + bx) / 2) * W, my = ((ay + by) / 2) * H
  const L = 0.07 * Math.min(W, H)
  return { x1: (mx - nx * L * 0.4) / W, y1: (my - ny * L * 0.4) / H, x2: (mx + nx * L) / W, y2: (my + ny * L) / H }
}

export default function ZoneEditor({ camera, onSaved, onError }) {
  const [draft, setDraft] = useState(() => structuredClone(camera))
  const [mode, setMode] = useState('idle') // idle | zone | line | calibrate
  const [points, setPoints] = useState([])
  const [frameUrl, setFrameUrl] = useState(() => api.frameUrl(camera.id))
  const [frameOk, setFrameOk] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState('')
  const svgRef = useRef(null)
  const size = camera.size || [1280, 720]

  useEffect(() => {
    setDraft(structuredClone(camera)); setMode('idle'); setPoints([]); setSaved('')
    setFrameUrl(api.frameUrl(camera.id)); setFrameOk(true)
  }, [camera.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const click = (e) => {
    if (mode === 'idle') return
    const r = svgRef.current.getBoundingClientRect()
    const p = [r4((e.clientX - r.left) / r.width), r4((e.clientY - r.top) / r.height)]
    const next = [...points, p]
    if (mode === 'calibrate' && next.length === 4) {
      setDraft((d) => ({ ...d, calibration: { image_points_norm: next, width_m: d.calibration?.width_m || 4, length_m: d.calibration?.length_m || 6 } }))
      setMode('idle'); setPoints([])
      return
    }
    if (mode === 'line' && next.length === 2) {
      setDraft((d) => ({ ...d, lines: [...(d.lines || []), { id: undefined, name: `Line ${(d.lines || []).length + 1}`, points_norm: next }] }))
      setMode('idle'); setPoints([])
      return
    }
    setPoints(next)
  }
  const finishZone = () => {
    const n = (draft.zones || []).length + 1
    setDraft((d) => ({ ...d, zones: [...(d.zones || []), { id: undefined, name: `Zone ${n}`, kind: 'restricted', polygon_norm: points, base_score: 75, dwell_limit_s: 8, area_m2: '' }] }))
    setMode('idle'); setPoints([])
  }
  const setZone = (i, patch) => setDraft((d) => ({ ...d, zones: d.zones.map((z, k) => (k === i ? { ...z, ...patch } : z)) }))
  const removeZone = (i) => setDraft((d) => ({ ...d, zones: d.zones.filter((_, k) => k !== i) }))
  const setLine = (i, patch) => setDraft((d) => ({ ...d, lines: d.lines.map((l, k) => (k === i ? { ...l, ...patch } : l)) }))
  const removeLine = (i) => setDraft((d) => ({ ...d, lines: d.lines.filter((_, k) => k !== i) }))
  const setCal = (patch) => setDraft((d) => ({ ...d, calibration: { ...d.calibration, ...patch } }))
  const opts = { ...DEFAULT_OPTIONS, ...(draft.options || {}) }
  const setOpt = (patch) => setDraft((d) => ({ ...d, options: { ...opts, ...patch } }))

  const save = async () => {
    setSaving(true); setSaved('')
    try {
      const out = await api.updateCamera(camera.id, cameraBody(draft))
      setSaved('Saved. The camera restarts with the new settings in a few seconds.')
      onSaved?.(out)
      setTimeout(() => { setFrameUrl(api.frameUrl(camera.id)); setFrameOk(true) }, 4000)
    } catch (e) { onError(e.message) }
    setSaving(false)
  }
  const poly = (pts) => pts.map(([x, y]) => `${x},${y}`).join(' ')
  const cal = draft.calibration?.image_points_norm
  const hint = {
    zone: 'Click around the area on the picture. Three or more points, then “Finish zone”.',
    line: 'Click the two ends of the counting line. Crossing it towards the arrow counts as IN; “Swap IN/OUT” flips it.',
    calibrate: 'Click 4 floor corners of a rectangle you know the size of, in this order: near-left, near-right, far-right, far-left.',
  }[mode]

  return (
    <div className="zone-editor">
      <div className="form-grid">
        <label>Name<input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} maxLength={60} /></label>
        <label>Source<input value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })} maxLength={500} /></label>
        <label className="check"><input type="checkbox" checked={draft.enabled !== false} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /> Enabled</label>
      </div>
      <p className="quiet small">Source: <code>0</code> laptop webcam · <code>1</code> USB webcam · <code>browser</code> camera opened by this browser · <code>clips/name.mp4</code> video file · <code>rtsp://user:pass@ip:554/stream</code> IP camera · <code>mock</code> simulated crowd</p>

      <div className="form-grid">
        <label>Detector
          <select value={opts.model} onChange={(e) => setOpt({ model: e.target.value })}>
            <option value="fast">Fast: NanoDet-Plus (smooth live tracking)</option>
            <option value="accurate">Accurate: YOLOX-S (small, distant people; more CPU)</option>
            <option value="crowd">Dense crowd: YOLOX-M on tiles (packed rooms filmed from above; slow, for videos)</option>
          </select>
        </label>
        <label>Max analysed frames per second<input type="number" min="1" max="30" value={opts.max_fps} onChange={(e) => setOpt({ max_fps: e.target.value })} /></label>
        <label className="check"><input type="checkbox" checked={opts.trails} onChange={(e) => setOpt({ trails: e.target.checked })} /> Movement trails</label>
        <label className="check"><input type="checkbox" checked={opts.heatmap} onChange={(e) => setOpt({ heatmap: e.target.checked })} /> Density heat overlay</label>
      </div>
      <p className="quiet small">When Ultralytics YOLO26 is installed (install_yolo.bat), every camera uses it instead and this choice has no effect.</p>

      <div className="toolbar">
        <button className="btn" disabled={mode !== 'idle'} onClick={() => { setMode('zone'); setPoints([]) }}>Draw new zone</button>
        <button className="btn" disabled={mode !== 'zone' || points.length < 3} onClick={finishZone}>Finish zone ({points.length} points)</button>
        <button className="btn" disabled={mode !== 'idle'} onClick={() => { setMode('line'); setPoints([]) }}>Draw counting line</button>
        <button className="btn" disabled={mode !== 'idle'} onClick={() => { setMode('calibrate'); setPoints([]) }}>Calibrate floor (4 clicks)</button>
        <button className="btn" disabled={!points.length} onClick={() => setPoints(points.slice(0, -1))}>Undo point</button>
        <button className="btn" disabled={mode === 'idle'} onClick={() => { setMode('idle'); setPoints([]) }}>Cancel</button>
        <button className="btn" onClick={() => { setFrameUrl(api.frameUrl(camera.id)); setFrameOk(true) }}>Refresh frame</button>
      </div>
      {hint && <p className="hint">{hint}</p>}

      <div className={`editor ${mode !== 'idle' ? 'drawing' : ''}`}>
        {frameOk
          ? <img src={frameUrl} alt="Still frame from this camera" onError={() => setFrameOk(false)} />
          : <div className="noframe">No frame yet. The camera must be enabled and running: save, wait a few seconds, then “Refresh frame”.</div>}
        <svg ref={svgRef} viewBox="0 0 1 1" preserveAspectRatio="none" onClick={click} role="img" aria-label="Zones and lines on the camera view">
          {(draft.zones || []).map((z, i) => z.polygon_norm && (
            <polygon key={i} points={poly(z.polygon_norm)} fill={z.kind === 'restricted' ? '#f8514933' : '#58a6ff33'}
              stroke={z.kind === 'restricted' ? '#f85149' : SERIES[i % SERIES.length]} strokeWidth="2" vectorEffect="non-scaling-stroke" />
          ))}
          {(draft.lines || []).map((l, i) => {
            const a = inArrow(l.points_norm, size)
            return (
              <g key={`l${i}`}>
                <polyline points={poly(l.points_norm)} stroke="#ffe650" strokeWidth="4" vectorEffect="non-scaling-stroke" />
                <line {...a} stroke="#ffe650" strokeWidth="3" vectorEffect="non-scaling-stroke" />
                <circle cx={a.x2} cy={a.y2} r="0.008" fill="#ffe650" />
              </g>
            )
          })}
          {cal && <polygon points={poly(cal)} fill="none" stroke="#ffd33d" strokeDasharray="6 4" strokeWidth="2" vectorEffect="non-scaling-stroke" />}
          {points.length > 0 && <polyline points={poly(points)} fill="none" stroke="#ffffff" strokeWidth="2" vectorEffect="non-scaling-stroke" />}
          {points.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="0.007" fill="#ffffff" />)}
        </svg>
        {(draft.zones || []).map((z, i) => z.polygon_norm && (
          <span key={i} className="zone-tag" style={{ left: `${z.polygon_norm[0][0] * 100}%`, top: `${z.polygon_norm[0][1] * 100}%` }}>{z.name}</span>
        ))}
        {(draft.lines || []).map((l, i) => {
          const a = inArrow(l.points_norm, size)
          return <span key={`t${i}`} className="zone-tag line-tag" style={{ left: `${a.x2 * 100}%`, top: `${a.y2 * 100}%` }}>IN · {l.name}</span>
        })}
      </div>

      <h4>Zones</h4>
      {!(draft.zones || []).length && <p className="quiet small">No zones yet. Use “Draw new zone”.</p>}
      <div className="zone-list">
        {(draft.zones || []).map((z, i) => (
          <div key={i} className="zone-row">
            <input aria-label="Zone name" value={z.name} onChange={(e) => setZone(i, { name: e.target.value })} maxLength={40} />
            <select aria-label="Zone type" value={z.kind} onChange={(e) => setZone(i, { kind: e.target.value })}>
              <option value="crowd">Crowd zone (density, Crush Clock)</option>
              <option value="restricted">Restricted zone (entry, loitering)</option>
            </select>
            <label>Area m²<input type="number" min="0" step="0.1" value={z.area_m2 ?? ''} onChange={(e) => setZone(i, { area_m2: e.target.value })}
              placeholder={cal ? 'from calibration' : 'needed for density'} /></label>
            {z.kind === 'restricted' && <>
              <label>Entry score<input type="number" min="0" max="100" value={z.base_score ?? 55} onChange={(e) => setZone(i, { base_score: e.target.value })} /></label>
              <label>Dwell limit s<input type="number" min="1" max="3600" value={z.dwell_limit_s ?? ''} onChange={(e) => setZone(i, { dwell_limit_s: e.target.value })} /></label>
            </>}
            <button className="btn danger" onClick={() => removeZone(i)}>Delete</button>
          </div>
        ))}
      </div>

      <h4>Counting lines</h4>
      {!(draft.lines || []).length && <p className="quiet small">No counting lines. Use “Draw counting line” across a doorway, gate or corridor to count people IN and OUT.</p>}
      <div className="zone-list">
        {(draft.lines || []).map((l, i) => (
          <div key={i} className="line-row">
            <input aria-label="Line name" value={l.name} onChange={(e) => setLine(i, { name: e.target.value })} maxLength={40} />
            <button className="btn" onClick={() => setLine(i, { points_norm: [l.points_norm[1], l.points_norm[0]] })}>Swap IN/OUT</button>
            <button className="btn danger" onClick={() => removeLine(i)}>Delete</button>
          </div>
        ))}
      </div>

      <h4>Floor calibration {cal ? '' : '(optional)'}</h4>
      {cal ? (
        <div className="row">
          <label>Width near-left → near-right (m)<input type="number" min="0.1" step="0.1" value={draft.calibration.width_m} onChange={(e) => setCal({ width_m: e.target.value })} /></label>
          <label>Length near-left → far-left (m)<input type="number" min="0.1" step="0.1" value={draft.calibration.length_m} onChange={(e) => setCal({ length_m: e.target.value })} /></label>
          <button className="btn danger" onClick={() => setDraft((d) => ({ ...d, calibration: null }))}>Remove calibration</button>
        </div>
      ) : <p className="quiet small">Without calibration, give each crowd zone its real area in m²; walking speeds are then estimated from each person's height. With it, areas and speeds are in real metres.</p>}

      <div className="row save-row">
        <button className="btn primary" onClick={save} disabled={saving || mode !== 'idle'}>{saving ? 'Saving…' : 'Save camera'}</button>
        {saved && <span className="ok-text">{saved}</span>}
      </div>
    </div>
  )
}
