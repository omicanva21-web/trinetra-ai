import { withToken } from '../api.js'
import { LEVEL_COLOR } from '../format.js'
import VideoPanel from './VideoPanel.jsx'

function zoneValue(z) {
  if (z.kind === 'crowd') {
    if (z.density == null) return `${z.count} people`
    const eta = z.eta_s != null && z.trend === 'rising' ? ` · ${Math.floor(z.eta_s / 60)}:${String(Math.floor(z.eta_s % 60)).padStart(2, '0')} to danger` : ''
    return `${z.density.toFixed(2)}/m²${z.trend === 'critical' ? ' · AT DANGER' : eta}`
  }
  return z.count ? `${z.count} inside · ${Math.round(z.max_dwell_s)}s` : 'clear'
}

export default function CameraTile({ camera, state, onOpen, epoch = 0 }) {
  const level = state?.level || 'LOW'
  const status = state?.status
  const tr = state?.tracking
  const upload = camera.source_kind === 'upload'
  return (
    <figure className={`tile level-${level}`}>
      {status && status.startsWith('error')
        ? <div className="novideo"><b>No video</b><span>{status.replace(/^error: /, '')}</span><span className="quiet small">Retrying every 3 s. Fix or disable this camera on the Setup page.</span></div>
        : <img src={withToken(`/stream/${camera.id}.mjpg?e=${epoch}`)} alt={`Live view: ${camera.name}`} onClick={onOpen} title="Open in Tracking" />}
      <figcaption>
        <div className="row">
          <span className="name">{camera.name}</span>
          {camera.simulated && <span className="badge sim">SIMULATED</span>}
          {upload && <span className="badge sim">UPLOADED VIDEO</span>}
          <span className={`badge lvl ${level}`}>{level}</span>
          <span className="spacer" />
          <span className="stat">{state ? `${state.people} people` : '—'}</span>
          {state?.vehicles ? <span className="stat">{state.vehicles} vehicles</span> : null}
          <span className="stat quiet">{state?.fps ? `${state.fps} fps` : ''}</span>
        </div>
        {!upload && status && status !== 'running' && !status.startsWith('error') && <div className="badge warn wide">{status}</div>}
        {state?.detector && <div className="quiet small">{state.detector}</div>}
        {upload && <VideoPanel camera={camera} state={state} compact />}
        {tr && !upload && (
          <div className="row small tracksum">
            <span><b>{tr.active_count}</b> tracked</span>
            <span><b>{tr.unique}</b> unique</span>
            {tr.lines.map((l) => <span key={l.id}>{l.name}: <b>IN {l.in}</b> · <b>OUT {l.out}</b></span>)}
          </div>
        )}
        <div className="zonebars">
          {(state?.zones || []).map((z) => (
            <div key={z.id} className="zonebar" title={(z.reasons || []).map((r) => `${r.text} (+${r.points})`).join('\n') || 'No risk signals'}>
              <span className="zname">{z.name}</span>
              <span className="track"><i style={{ width: `${Math.max(2, z.score)}%`, background: LEVEL_COLOR[z.level] }} /></span>
              <span className="zval">{zoneValue(z)}</span>
            </div>
          ))}
        </div>
      </figcaption>
    </figure>
  )
}
