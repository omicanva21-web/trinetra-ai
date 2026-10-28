import { useEffect, useState } from 'react'

// Shows time to danger density. Ticks down locally between server updates (every 0.5 s).
export default function CrushClock({ etaS, trend, big = false }) {
  const [received, setReceived] = useState(() => Date.now())
  const [, setNow] = useState(0)
  useEffect(() => { setReceived(Date.now()) }, [etaS])
  useEffect(() => { const id = setInterval(() => setNow((n) => n + 1), 250); return () => clearInterval(id) }, [])

  if (trend === 'critical') return <div className={`clock critical ${big ? 'big' : ''}`}>AT DANGER LINE</div>
  if (etaS == null) {
    const label = trend === 'falling' ? 'Easing' : trend === 'stable' ? 'Stable' : trend === 'slow_rise' ? 'Rising slowly (over 10 min to danger)' : 'Measuring…'
    return <div className={`clock calm ${big ? 'big' : ''}`}>{label}</div>
  }
  const left = Math.max(0, etaS - (Date.now() - received) / 1000)
  const mm = Math.floor(left / 60), ss = Math.floor(left % 60)
  const tone = left <= 30 ? 'critical' : left <= 120 ? 'warn' : 'calm'
  return (
    <div className={`clock ${tone} ${big ? 'big' : ''}`} title="Estimated time until this zone reaches danger density">
      <span className="digits">{mm}:{String(ss).padStart(2, '0')}</span>
      <span className="unit">to danger</span>
    </div>
  )
}
