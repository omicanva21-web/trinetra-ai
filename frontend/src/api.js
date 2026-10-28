// REST helpers. The operator token (only needed when the backend sets OPERATOR_TOKEN) lives in localStorage.
export function readToken() {
  try { return localStorage.getItem('trinetra_token') || '' } catch { return '' }
}

export function saveToken(token) {
  try { localStorage.setItem('trinetra_token', token) } catch { /* private mode: token lives for this page only */ }
}

export function withToken(url) {
  const t = readToken()
  return t ? `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(t)}` : url
}

async function request(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Operator-Token': readToken(), ...(options.headers || {}) },
  })
  if (!res.ok) {
    let detail = await res.text()
    try {
      const j = JSON.parse(detail)
      detail = Array.isArray(j.detail) ? j.detail.map((d) => `${d.loc?.slice(1).join('.')}: ${d.msg}`).join('; ') : j.detail
    } catch { /* plain text error */ }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

const json = (method, body) => ({ method, body: JSON.stringify(body) })

export const api = {
  config: () => request('/api/config'),
  cameras: () => request('/api/cameras'),
  addCamera: (body) => request('/api/cameras', json('POST', body)),
  updateCamera: (id, body) => request(`/api/cameras/${id}`, json('PUT', body)),
  deleteCamera: (id) => request(`/api/cameras/${id}`, { method: 'DELETE' }),
  frameUrl: (id) => withToken(`/api/cameras/${id}/frame.jpg?t=${Date.now()}`),
  profiles: () => request('/api/profiles'),
  updateProfile: (name, body) => request(`/api/profiles/${name}`, json('PUT', body)),
  setProfile: (name) => request('/api/profile', json('POST', { name })),
  incidents: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null))
    return request(`/api/incidents?${q}`)
  },
  incident: (id) => request(`/api/incidents/${id}`),
  act: (id, action, note = '') => request(`/api/incidents/${id}/action`, json('POST', { action, note })),
  metrics: (minutes = 10) => request(`/api/metrics?minutes=${minutes}`),
  stats: (windowMin = 60, params = {}) => request(`/api/stats?${new URLSearchParams({ window_min: windowMin, ...params })}`),
  tracks: (cameraId, recent = 40) => request(`/api/cameras/${cameraId}/tracks?recent=${recent}`),
  focus: (cameraId, trackId) => request(`/api/cameras/${cameraId}/focus`, json('POST', { track_id: trackId })),
  trackingStats: (cameraId, windowMin = 30) => request(`/api/tracking/stats?camera_id=${cameraId}&window_min=${windowMin}`),
  video: (cameraId) => request(`/api/cameras/${cameraId}/video`),
  videoControl: (cameraId, action, extra = {}) => request(`/api/cameras/${cameraId}/video/control`, json('POST', { action, ...extra })),
  removeVideo: (cameraId) => request(`/api/cameras/${cameraId}/video`, { method: 'DELETE' }),
  videoTimeline: (cameraId) => request(`/api/cameras/${cameraId}/video/timeline`),
}

// Upload a video file as the raw request body (XHR, for a progress bar). Resolves with the video status.
export function uploadVideo(cameraId, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/cameras/${cameraId}/video`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name))
    const token = readToken()
    if (token) xhr.setRequestHeader('X-Operator-Token', token)
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total) }
    xhr.upload.onload = () => onProgress?.(1)
    xhr.onload = () => {
      let body = null
      try { body = JSON.parse(xhr.responseText) } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body)
      else reject(new Error(body?.detail ? (Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join('; ') : body.detail) : `Upload failed (${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error('The upload could not reach Trinetra. Is it still running? (A file over the size limit can also cause this.)'))
    xhr.send(file)
  })
}
