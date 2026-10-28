import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { readToken } from './api.js'

// Opens a camera in the browser (getUserMedia) and streams JPEG frames to Trinetra over
// /ws/camera/{id}, for cameras whose source is "browser". It lives at the top of the app, so it keeps
// streaming while you switch pages. Browsers only allow cameras on secure pages; http://localhost counts.
const Ctx = createContext(null)
export const useCameraSender = () => useContext(Ctx)

const MAX_WIDTH = 960 // enough detail for detection, small enough to send 15 frames a second

function friendlyError(e) {
  if (e?.name === 'NotAllowedError') return 'Camera permission was blocked. Click the camera icon in the address bar, allow the camera, then press Start camera again.'
  if (e?.name === 'NotReadableError') return 'The camera is busy in another app (Zoom, Teams, the Camera app) or another camera in Trinetra uses it directly. Close it and press Start camera again.'
  if (e?.name === 'NotFoundError' || e?.name === 'OverconstrainedError') return 'No camera found. Plug one in or pick another device.'
  return `${e?.name || 'Error'}: ${e?.message || e}`
}

export function CameraSenderProvider({ children }) {
  const [state, setState] = useState({ cameraId: null, running: false, starting: false, sentFps: 0, size: null, error: '', deviceId: '', label: '' })
  const ref = useRef(null)

  const stop = useCallback(() => {
    const r = ref.current
    if (r) {
      r.stopped = true
      clearTimeout(r.timer)
      try { r.ws.close() } catch { /* already closed */ }
      r.stream.getTracks().forEach((t) => t.stop())
    }
    ref.current = null
    setState((s) => ({ ...s, cameraId: null, running: false, starting: false, sentFps: 0 }))
  }, [])

  const start = useCallback(async (cameraId, deviceId = '', fps = 15) => {
    stop()
    if (!navigator.mediaDevices?.getUserMedia) {
      setState((s) => ({ ...s, error: 'This page cannot use a camera. Open Trinetra at http://localhost:8000 in Chrome or Edge.' }))
      return
    }
    setState((s) => ({ ...s, starting: true, error: '' }))
    let stream
    try {
      const size = { width: { ideal: 1280 }, height: { ideal: 720 } }
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: deviceId ? { ...size, deviceId: { exact: deviceId } } : size })
    } catch (e) {
      setState((s) => ({ ...s, starting: false, running: false, error: friendlyError(e) }))
      return
    }
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.srcObject = stream
    try { await video.play() } catch { /* some browsers start playback by themselves */ }
    const canvas = document.createElement('canvas')
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const token = readToken()
    const url = `${proto}://${location.host}/ws/camera/${cameraId}${token ? `?token=${encodeURIComponent(token)}` : ''}`
    const r = { stream, video, canvas, ws: null, stopped: false, sent: 0, since: performance.now(), busy: false, timer: 0, retries: 0 }
    ref.current = r

    const tick = () => {
      if (r.stopped) return
      r.timer = setTimeout(tick, 1000 / fps)
      const ws = r.ws
      if (!ws || ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 0 || r.busy || video.readyState < 2 || !video.videoWidth) return
      const scale = Math.min(1, MAX_WIDTH / video.videoWidth)
      canvas.width = Math.round(video.videoWidth * scale)
      canvas.height = Math.round(video.videoHeight * scale)
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
      r.busy = true
      canvas.toBlob((blob) => {
        r.busy = false
        if (blob && ws.readyState === WebSocket.OPEN) { ws.send(blob); r.sent += 1 }
      }, 'image/jpeg', 0.75)
      const now = performance.now()
      if (now - r.since >= 1000) {
        const f = (r.sent * 1000) / (now - r.since)
        r.sent = 0
        r.since = now
        setState((s) => ({ ...s, sentFps: Math.round(f * 10) / 10, size: [canvas.width, canvas.height] }))
      }
    }
    // (Re)connect to Trinetra; if the server restarts, keep the camera open and reconnect by itself.
    const connect = () => {
      if (r.stopped) return
      const ws = new WebSocket(url)
      r.ws = ws
      ws.onopen = () => {
        r.retries = 0
        setState((s) => ({ ...s, starting: false, running: true, error: '' }))
      }
      ws.onclose = () => {
        if (r.stopped) return
        r.retries += 1
        if (r.retries > 10) {
          stop()
          setState((s) => ({ ...s, error: 'Lost the connection to Trinetra. Check that it is running and that this camera\'s source is "browser" on the Setup page, then press Start camera.' }))
          return
        }
        setState((s) => ({ ...s, running: false, starting: true, sentFps: 0 }))
        setTimeout(connect, 2000)
      }
    }
    connect()
    tick()
    const label = stream.getVideoTracks()[0]?.label || 'camera'
    setState({ cameraId, running: false, starting: true, sentFps: 0, size: null, error: '', deviceId, label })
  }, [stop])

  const listDevices = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices()
      return all.filter((d) => d.kind === 'videoinput').map((d, i) => ({ id: d.deviceId, label: d.label || `Camera ${i + 1}` }))
    } catch { return [] }
  }, [])

  useEffect(() => () => stop(), [stop])
  return <Ctx.Provider value={{ ...state, start, stop, listDevices }}>{children}</Ctx.Provider>
}
