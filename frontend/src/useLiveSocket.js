import { useEffect, useRef, useState } from 'react'

// One WebSocket to /ws with automatic reconnect (1 s, 2 s, 4 s ... up to 10 s).
export function useLiveSocket(onMessage) {
  const [connected, setConnected] = useState(false)
  const handler = useRef(onMessage)
  handler.current = onMessage

  useEffect(() => {
    let ws, timer, delay = 1000, closed = false
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => { setConnected(true); delay = 1000 }
      ws.onmessage = (e) => { try { handler.current(JSON.parse(e.data)) } catch (err) { console.error(err) } }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) { timer = setTimeout(connect, delay); delay = Math.min(delay * 2, 10000) }
      }
    }
    connect()
    return () => { closed = true; clearTimeout(timer); ws && ws.close() }
  }, [])

  return connected
}
