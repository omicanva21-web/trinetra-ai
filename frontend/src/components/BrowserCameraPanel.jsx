import { useEffect, useState } from 'react'
import { useCameraSender } from '../cameraSender.jsx'

// Controls for cameras whose frames come from this browser, and the switch to that mode when
// Trinetra cannot open a webcam directly.
export default function BrowserCameraPanel({ camera, onSwitchSource, busy }) {
  const sender = useCameraSender()
  const [devices, setDevices] = useState([])
  const [deviceId, setDeviceId] = useState(sender.deviceId || '')
  const mine = sender.cameraId === camera.id
  const isBrowser = String(camera.source) === 'browser'

  useEffect(() => { sender.listDevices().then(setDevices) }, [sender.running]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!isBrowser) {
    if (camera.source_kind !== 'webcam') return null
    const failing = String(camera.status || '').startsWith('error')
    return (
      <div className={`note ${failing ? 'warn' : ''} row`}>
        <span className="grow">
          {failing
            ? <>Trinetra cannot open this webcam directly ({String(camera.status).replace(/^error: /, '')}). Let the browser open it instead.</>
            : <>Trinetra reads webcam {camera.source} directly. If the picture stays black or frozen, let the browser open the camera instead.</>}
        </span>
        <button className="btn primary" disabled={busy} onClick={() => onSwitchSource('browser', deviceId)}>Use browser camera</button>
      </div>
    )
  }

  const status = sender.error
    ? <span className="err-text">{sender.error}</span>
    : mine && sender.running
      ? <span className="ok-text">Streaming {sender.sentFps} fps{sender.size ? ` · ${sender.size[0]}×${sender.size[1]}` : ''} from {sender.label}</span>
      : mine && sender.starting
        ? <span className="quiet">Opening the camera… allow access if the browser asks.</span>
        : sender.running
          ? <span className="quiet">The browser camera is streaming to another Trinetra camera. Starting here moves it.</span>
          : <span className="quiet">Press Start camera; the browser will ask for permission the first time.</span>

  return (
    <div className="note browsercam">
      <div className="row">
        <b>Browser camera</b>
        <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} aria-label="Camera device">
          <option value="">Default camera</option>
          {devices.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        {mine && (sender.running || sender.starting)
          ? <button className="btn danger" onClick={sender.stop}>Stop camera</button>
          : <button className="btn primary" onClick={() => sender.start(camera.id, deviceId, Math.min(15, camera.options?.max_fps || 15))}>Start camera</button>}
        <span className="spacer" />
        <button className="link" disabled={busy} onClick={() => { if (mine) sender.stop(); onSwitchSource('0') }}>Switch to direct webcam</button>
      </div>
      <div className="small">{status}</div>
      <div className="quiet small">Keep this tab open and visible: browsers slow down hidden tabs. A phone camera works too through apps such as DroidCam or Iriun, which appear here as a camera device.</div>
    </div>
  )
}
