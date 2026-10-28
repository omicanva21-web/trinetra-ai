import { useEffect, useRef, useState } from 'react'
import { api, uploadVideo } from '../api.js'
import { VIDEO_STATE, megabytes, mmss } from '../format.js'
import { cameraBody } from './ZoneEditor.jsx'

// Camera 4: upload a recording and run the real detection + tracking pipeline on it, with playback controls.
const ACCEPT = '.mp4,.m4v,.mov,.avi,.mkv,.webm,video/mp4,video/quicktime,video/x-msvideo,video/x-matroska,video/webm'
const EXTS = ['mp4', 'm4v', 'mov', 'avi', 'mkv', 'webm']
const SPEEDS = [[0.5, '0.5×'], [1, '1× real time'], [2, '2×'], [4, '4×'], [0, 'Max']]
// Detection mode for this camera; Dense crowd analyses fewer frames per second because each one costs ~20 model runs
const MODES = [
  ['fast', 'Fast', 'NanoDet: people walking past a camera at eye level; smooth on a laptop', 15],
  ['accurate', 'Accurate', 'YOLOX-S: smaller, more distant people; about 6× more CPU', 8],
  ['crowd', 'Dense crowd', 'YOLOX-M on 20 enlarged tiles: packed rooms filmed from above (halls, stands). Slow: a few seconds per frame', 3],
]
const CAN = {
  upload: ['empty', 'ready', 'completed', 'stopped', 'error'],
  start: ['ready', 'completed', 'stopped', 'error'],
  restart: ['processing', 'paused', 'completed', 'stopped', 'error'],
  stop: ['processing', 'paused'],
}

// Newest of: the video status in the live state message, or the answer to the last button press.
function useVideoStatus(camera, state) {
  const [answer, setAnswer] = useState(null)
  const fromState = state?.video ? { v: state.video, at: state.ts || 0 } : null
  const pick = [answer, fromState, camera?.video ? { v: camera.video, at: 0 } : null].filter(Boolean)
    .sort((a, b) => b.at - a.at)[0]
  return [pick?.v || null, (v) => setAnswer({ v, at: Date.now() / 1000 })]
}

// Timeline of the current run, one sample per second of video (for the charts).
export function useVideoTimeline(cameraId, video) {
  const [data, setData] = useState(null)
  const session = video?.session
  const st = video?.state
  useEffect(() => {
    if (!cameraId || !st) return undefined
    let alive = true
    const load = () => api.videoTimeline(cameraId).then((d) => { if (alive) setData(d) }).catch(() => {})
    load()
    const id = st === 'processing' ? setInterval(load, 2000) : null
    return () => { alive = false; if (id) clearInterval(id) }
  }, [cameraId, session, st])
  return data
}

export default function VideoPanel({ camera, state, compact = false }) {
  const [video, setVideo] = useVideoStatus(camera, state)
  const [upload, setUpload] = useState(null) // { name, pct, checking }
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [dragging, setDragging] = useState(false)
  const input = useRef(null)
  useEffect(() => { if (!confirmRemove) return undefined; const id = setTimeout(() => setConfirmRemove(false), 6000); return () => clearTimeout(id) }, [confirmRemove])

  const vs = video?.state || 'empty'
  const shown = upload ? (upload.checking ? 'checking' : 'uploading') : vs
  const hasFile = !!video?.file
  const tr = state?.tracking
  const maxMb = video?.max_upload_mb || 1024
  const offline = String(state?.detector || camera?.detector || '').startsWith('analytics offline')

  const send = async (file) => {
    setErr('')
    if (!file) return
    const ext = (file.name.split('.').pop() || '').toLowerCase()
    if (!EXTS.includes(ext) && !file.type.startsWith('video/')) {
      setErr(`“${file.name}” is not a supported video. Accepted formats: ${video?.accepted || 'MP4, MOV, AVI, MKV or WEBM'}.`)
      return
    }
    if (file.size === 0) { setErr('That file is empty.'); return }
    if (file.size > maxMb * 1048576) {
      setErr(`This video is ${megabytes(file.size)}; the limit is ${maxMb} MB. Trim it, or raise TRINETRA_MAX_UPLOAD_MB in .env.`)
      return
    }
    setUpload({ name: file.name, pct: 0, checking: false })
    try {
      const v = await uploadVideo(camera.id, file, (p) => setUpload((u) => (u ? { ...u, pct: p, checking: p >= 1 } : u)))
      setVideo(v)
    } catch (e) {
      setErr(e.message)
    }
    setUpload(null)
    if (input.current) input.current.value = ''
  }
  const act = async (action, extra) => {
    setErr(''); setBusy(action)
    try { setVideo(await api.videoControl(camera.id, action, extra)) } catch (e) { setErr(e.message.replace(/^\d+: /, '')) }
    setBusy('')
  }
  const model = camera?.options?.model || 'fast'
  const setMode = async (value) => {
    const m = MODES.find(([k]) => k === value)
    if (!m || value === model) return
    setErr(''); setBusy('mode')
    try {
      // saving restarts this camera with the new detector; the uploaded video stays loaded (READY)
      await api.updateCamera(camera.id, { ...cameraBody(camera), options: { ...cameraBody(camera).options, model: value, max_fps: m[3] } })
    } catch (e) { setErr(e.message.replace(/^\d+: /, '')) }
    setBusy('')
  }
  const remove = async () => {
    if (!confirmRemove) { setConfirmRemove(true); return }
    setConfirmRemove(false); setErr(''); setBusy('remove')
    try { setVideo(await api.removeVideo(camera.id)) } catch (e) { setErr(e.message.replace(/^\d+: /, '')) }
    setBusy('')
  }

  const canUpload = !upload && CAN.upload.includes(vs)
  const pct = video?.progress != null ? Math.round(video.progress * 1000) / 10 : null
  const drop = (e) => { e.preventDefault(); setDragging(false); if (canUpload) send(e.dataTransfer.files?.[0]) }

  return (
    <div className={`videopanel ${compact ? 'compact' : ''} ${dragging ? 'drag' : ''}`}
      onDragOver={(e) => { e.preventDefault(); if (canUpload) setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={drop}>
      <div className="row">
        <span className={`badge vstate vs-${shown}`}>{VIDEO_STATE[shown] || shown.toUpperCase()}</span>
        <span className="vfile" title={video?.file || ''}>{upload ? upload.name : video?.file || 'No video uploaded'}</span>
        <span className="spacer" />
        <label className="speed" title={MODES.find(([k]) => k === model)?.[2]}>
          <span>Detection</span>
          <select value={model} disabled={!!busy || !!upload || vs === 'processing' || vs === 'paused'} onChange={(e) => setMode(e.target.value)} aria-label="Detection mode">
            {MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label className="speed" title="Playback speed while processing. If the computer is slower, the video simply plays slower; every analysed frame is still processed.">
          <span>Speed</span>
          <select value={video?.speed ?? 1} disabled={!hasFile || !!busy} onChange={(e) => act('speed', { speed: Number(e.target.value) })} aria-label="Processing speed">
            {SPEEDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </div>

      <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => send(e.target.files?.[0])} aria-label="Choose a video file" />
      <div className="vbuttons">
        <button className="btn primary" disabled={!canUpload} onClick={() => input.current?.click()}
          title={canUpload ? 'Choose a video from this computer (or drop it on this card)' : 'Stop processing first'}>Upload video</button>
        <button className="btn resolve" disabled={!hasFile || !!busy || !CAN.start.includes(vs)} onClick={() => act('start')}>Start processing</button>
        <button className="btn" disabled={vs !== 'processing' || !!busy} onClick={() => act('pause')}>Pause</button>
        <button className="btn" disabled={vs !== 'paused' || !!busy} onClick={() => act('resume')}>Resume</button>
        <button className="btn" disabled={!hasFile || !!busy || !CAN.restart.includes(vs)} onClick={() => act('restart')}>Restart</button>
        <button className="btn" disabled={!CAN.stop.includes(vs) || !!busy} onClick={() => act('stop')}>Stop</button>
        <button className={`btn danger ${confirmRemove ? 'confirm' : ''}`} disabled={!hasFile || !!busy || !!upload} onClick={remove}>
          {confirmRemove ? 'Click again to remove' : 'Remove'}
        </button>
      </div>

      {upload && (
        <div className="vprogress uploading" aria-label="Upload progress">
          <i style={{ width: `${Math.round(upload.pct * 100)}%` }} />
          <span>{upload.checking ? 'Checking the video (decoding the first frames)…' : `Uploading ${Math.round(upload.pct * 100)}%`}</span>
        </div>
      )}
      {!upload && hasFile && (
        <div className="vprogress" title="Position in the video" aria-label="Video progress">
          <i style={{ width: `${pct ?? 0}%` }} />
          <span>{mmss(video.position_s)} / {mmss(video.duration_s)}{pct != null ? ` · ${pct.toFixed(pct < 10 ? 1 : 0)}%` : ''}</span>
        </div>
      )}

      {hasFile && (
        <div className="vstats">
          <span>People detected <b>{vs === 'processing' || vs === 'paused' ? (state?.people ?? 0) : '—'}</b></span>
          <span>People tracked <b>{tr?.unique ?? 0}</b></span>
          <span>Processing <b>{video.analysis_fps ? `${video.analysis_fps} fps` : '—'}</b></span>
          {!compact && <span>Video <b>{video.video_fps ? `${video.video_fps} fps` : '—'}</b></span>}
          {(tr?.lines || []).map((l) => <span key={l.id}>{l.name} <b>IN {l.in} · OUT {l.out}</b></span>)}
          {video.realtime != null && vs === 'processing' && <span title="Seconds of video processed per second">Playback <b>{video.realtime.toFixed(2)}× real time</b></span>}
        </div>
      )}
      {!compact && hasFile && (
        <div className="quiet small">
          {[video.width && `${video.width}×${video.height}`, video.container?.toUpperCase(), video.codec, megabytes(video.size_bytes),
            `${video.frames_analysed} frames analysed`].filter(Boolean).join(' · ')}
          {video.session_started ? ` · run started ${new Date(video.session_started * 1000).toLocaleTimeString()}` : ''}
        </div>
      )}

      {video?.model_loading && <div className="quiet small">Loading the detection model… {vs === 'processing' ? 'processing starts as soon as it is ready.' : ''}</div>}
      {err && <div className="err-text" role="alert">{err}</div>}
      {vs === 'error' && video?.message && <div className="err-text">Processing stopped: {video.message}. Press Restart to try again, or Remove and upload another file.</div>}
      {model !== 'crowd' && hasFile && (video.position_s || 0) > 5 && (tr?.unique ?? 0) < 3
        ? <div className="note warn small">Almost no one found so far. For a packed room filmed from above, {vs === 'processing' || vs === 'paused' ? 'press Stop, ' : ''}set <b>Detection → Dense crowd</b>, then Start processing.</div>
        : model !== 'crowd' && hasFile && !compact && <div className="quiet small">A packed room filmed from above (few people found)? Stop, set Detection to <b>Dense crowd</b>, then Start processing.</div>}
      {model === 'crowd' && hasFile && <div className="quiet small">Dense crowd: about 20 model runs per frame, {camera?.options?.max_fps || 3} frames analysed per second of video. Expect a few seconds per frame on a laptop; Speed only matters once the computer keeps up.</div>}
      {offline && <div className="note warn small">Person detection is not available ({String(state?.detector || camera?.detector).replace('analytics offline: ', '')}). The video plays, but no one can be detected or tracked until the model loads; see the README.</div>}
      {!hasFile && !upload && !err && (
        <div className="quiet small">
          {dragging ? 'Drop the video to upload it.' : `Choose a recording (${video?.accepted || 'MP4, MOV, AVI, MKV or WEBM'}, up to ${maxMb} MB) or drop it here. It stays on this computer.`}
        </div>
      )}
      {vs === 'completed' && <div className="ok-text small">{video?.message || 'Finished. Results stay on the Tracking and Analytics pages until you restart or remove the video.'}</div>}
    </div>
  )
}
