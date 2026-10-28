// Small shared helpers and the one colour system for risk levels and tracked people.
export const LEVEL_COLOR = { LOW: '#3fb950', MEDIUM: '#f0a020', HIGH: '#f85149' }
export const SERIES = ['#58a6ff', '#d2a8ff', '#56d4dd', '#ffa657', '#7ee787', '#ff7b72']
export const KIND_LABEL = {
  crowd_density: 'Crowd build-up', crowd_surge: 'Crowd surge', intrusion: 'Restricted-zone entry', loitering: 'Loitering',
}
export const STATUS_LABEL = {
  open: 'Open', acknowledged: 'Acknowledged', dispatched: 'Dispatched', false_alarm: 'False alarm', resolved: 'Resolved',
}
export const TREND_LABEL = {
  rising: 'rising', slow_rise: 'rising slowly', stable: 'stable', falling: 'easing', critical: 'at danger line', warming_up: 'measuring', unknown: '—',
}
export const SOURCE_LABEL = { webcam: 'Webcam', browser: 'Browser camera', stream: 'IP camera', file: 'Video file', simulated: 'Simulated', upload: 'Uploaded video' }
// Live = happening now; the rest are recordings or simulations (never added to "now" totals)
export const SOURCE_GROUP = { webcam: 'live', browser: 'live', stream: 'live', file: 'clip', simulated: 'simulated', upload: 'upload' }
export const VIDEO_STATE = {
  empty: 'NO VIDEO', uploading: 'UPLOADING', checking: 'CHECKING', ready: 'READY', processing: 'PROCESSING', paused: 'PAUSED',
  completed: 'COMPLETED', stopped: 'STOPPED', error: 'ERROR',
}
export const CLOSED = new Set(['resolved', 'false_alarm'])
export const RANK = { HIGH: 2, MEDIUM: 1, LOW: 0 }

// Same colour the video overlay uses for this tracking ID (golden-angle hue spacing).
export function trackColor(id) {
  return `hsl(${(id * 137.508) % 360}, 85%, 55%)`
}

export function clock(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function hm(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function duration(s) {
  if (s == null) return '—'
  s = Math.max(0, Math.round(s))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

export function ago(ts) {
  return `${duration(Date.now() / 1000 - ts)} ago`
}

// Position in a video: 75.4 -> "01:15" (or "1:02:03" past an hour)
export function mmss(s) {
  if (s == null || !Number.isFinite(s)) return '--:--'
  s = Math.max(0, Math.floor(s))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
  const two = (n) => String(n).padStart(2, '0')
  return h ? `${h}:${two(m)}:${two(sec)}` : `${two(m)}:${two(sec)}`
}

export function megabytes(bytes) {
  return bytes == null ? '—' : `${(bytes / 1048576).toFixed(bytes < 10485760 ? 1 : 0)} MB`
}
