import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { trackColor } from '../format.js'

const pts = (path) => path.map(([x, y]) => `${x},${y}`).join(' ')

// Where people walked: recent finished visits (thin) and people in view now (bold), on a still frame.
export default function TrajectoryMap({ camera, data, running }) {
  const [frame, setFrame] = useState(null)
  const [ok, setOk] = useState(true)
  useEffect(() => {
    if (!running) return undefined // no still frame exists until the camera delivers video
    const load = () => { setFrame(api.frameUrl(camera.id)); setOk(true) }
    load()
    const id = setInterval(load, 15000)
    return () => clearInterval(id)
  }, [camera.id, running])
  const finished = (data?.finished || []).filter((f) => f.path?.length > 1)
  const active = (data?.active || []).filter((a) => a.path?.length > 1)
  return (
    <div className="trajmap">
      <div className="editor">
        {ok && frame ? <img src={frame} alt="Still frame from this camera" onError={() => setOk(false)} /> : <div className="noframe">No still frame yet</div>}
        <svg viewBox="0 0 1 1" preserveAspectRatio="none" role="img" aria-label="Movement paths">
          {(camera.zones || []).filter((z) => z.polygon_norm).map((z) => (
            <polygon key={z.id} points={pts(z.polygon_norm)} fill={z.kind === 'restricted' ? '#f8514922' : '#58a6ff18'}
              stroke={z.kind === 'restricted' ? '#f85149' : '#58a6ff'} strokeWidth="1" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
          ))}
          {(camera.lines || []).map((l) => (
            <polyline key={l.id} points={pts(l.points_norm)} stroke="#ffe650" strokeWidth="3" vectorEffect="non-scaling-stroke" />
          ))}
          {finished.map((f) => (
            <polyline key={`f${f.track_id}-${f.ended_at || f.ended_wall}`} points={pts(f.path)} fill="none" stroke={trackColor(f.track_id)}
              strokeOpacity="0.55" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          ))}
          {active.map((a) => (
            <polyline key={`a${a.id}`} points={pts(a.path)} fill="none" stroke={trackColor(a.id)} strokeWidth="3.5" vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        {active.map((a) => {
          const [x, y] = a.path.at(-1)
          return <span key={a.id} className="traj-dot" style={{ left: `${x * 100}%`, top: `${y * 100}%`, background: trackColor(a.id) }}>#{a.id}</span>
        })}
      </div>
      <p className="quiet small">Bold: people in view now. Thin: the last {finished.length} people who left. Yellow: counting lines.</p>
    </div>
  )
}
