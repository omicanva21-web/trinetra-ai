import { clock, duration, mmss, trackColor } from '../format.js'

// Uploaded video: show where in the recording it happened, not the clock time it was processed
const when = (e, wall) => (e.video_ts != null ? <span className="quiet" title="Position in the video">▶ {mmss(e.video_ts)}</span> : <span className="quiet">{clock(wall)}</span>)

// Live list of what the tracker saw: line crossings and people leaving the view.
export default function ActivityFeed({ events }) {
  if (!events.length) return <p className="empty">Crossings and people leaving the view appear here as they happen.</p>
  return (
    <ol className="feed">
      {events.slice(0, 25).map((e, i) => {
        const tid = e.track_id
        const dot = <span className="swatch" style={{ background: trackColor(tid) }} />
        if (e.event === 'crossing') {
          return (
            <li key={i}>
              {when(e, e.wall)} {dot} <b>#{tid}</b> crossed <b>{e.line_name}</b>{' '}
              <span className={`dir ${e.direction}`}>{e.direction.toUpperCase()}</span>
            </li>
          )
        }
        return (
          <li key={i}>
            {when(e, e.ended_wall)} {dot} <b>#{tid}</b> {e.cls === 'vehicle' ? 'vehicle ' : ''}left after{' '}
            <b>{duration(e.duration_s)}</b> · {e.estimated ? '≈' : ''}{e.distance_m} m
            {e.zones?.length ? <> · was in {e.zones.join(', ')}</> : null}
          </li>
        )
      })}
    </ol>
  )
}
