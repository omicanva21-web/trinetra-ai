import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { KIND_LABEL, LEVEL_COLOR, SERIES, clock, hm, mmss } from '../format.js'

const AXIS = { stroke: '#8b98a8', fontSize: 11 }
const GRID = <CartesianGrid stroke="#2a313c" strokeDasharray="3 3" />
const TIP = {
  contentStyle: { background: '#161b22', border: '1px solid #2a313c', borderRadius: 6, color: '#e6edf3' },
  labelStyle: { color: '#8b98a8' },
}
const IN_COLOR = '#56d4dd'
const OUT_COLOR = '#d2a8ff'
const timeAxis = <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} tickFormatter={clock} {...AXIS} minTickGap={40} />
// Uploaded video: x = seconds into the recording, shown as mm:ss (never as a clock time)
const videoAxis = <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} tickFormatter={mmss} {...AXIS} minTickGap={40} />
const videoLabel = (t) => `${mmss(t)} in the video`

function Empty({ height, text = 'Waiting for data…' }) {
  return <div className="chart-empty" style={{ height }}>{text}</div>
}

// One crowd zone: density over time against the warn and danger lines.
export function ZoneDensityChart({ samples, zoneId, thresholds, height = 180 }) {
  const data = samples.filter((s) => s.zones?.[zoneId]?.density != null)
    .map((s) => ({ t: s.ts, density: s.zones[zoneId].density }))
  if (data.length < 2) return <Empty height={height} />
  const top = Math.max(thresholds ? thresholds.density_danger * 1.2 : 1, ...data.map((d) => d.density))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        {timeAxis}
        <YAxis domain={[0, Number(top.toFixed(2))]} {...AXIS} />
        <Tooltip {...TIP} labelFormatter={clock} formatter={(v) => [`${v.toFixed(2)} people/m²`, 'Density']} />
        {thresholds && <ReferenceLine y={thresholds.density_danger} stroke={LEVEL_COLOR.HIGH} strokeDasharray="5 4"
          label={{ value: `danger ${thresholds.density_danger}`, fill: LEVEL_COLOR.HIGH, fontSize: 10, position: 'insideTopRight' }} />}
        {thresholds && <ReferenceLine y={thresholds.density_warn} stroke={LEVEL_COLOR.MEDIUM} strokeDasharray="2 4"
          label={{ value: `warn ${thresholds.density_warn}`, fill: LEVEL_COLOR.MEDIUM, fontSize: 10, position: 'insideBottomRight' }} />}
        <Line type="monotone" dataKey="density" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

// People in view per camera, merged on a 2-second grid so the lines share one time axis.
export function PeopleChart({ history, cameras, height = 220 }) {
  const rows = new Map()
  for (const cam of cameras) {
    for (const s of history[cam.id] || []) {
      const t = Math.round(s.ts / 2) * 2
      const row = rows.get(t) || { t }
      row[cam.id] = s.people
      rows.set(t, row)
    }
  }
  const data = [...rows.values()].sort((a, b) => a.t - b.t)
  if (data.length < 2) return <Empty height={height} />
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        {timeAxis}
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip {...TIP} labelFormatter={clock} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {cameras.map((c, i) => (
          <Line key={c.id} type="monotone" dataKey={c.id} name={c.name} stroke={SERIES[i % SERIES.length]}
            strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

// One camera: people with a tracking ID over time, and everyone detected. `video`: samples carry vt (video time).
export function OccupancyChart({ samples, height = 200, video = false }) {
  const data = samples.map((s) => ({ t: video ? s.vt : s.ts, tracked: s.tracked ?? 0, detected: s.people }))
  if (data.length < 2) return <Empty height={height} text={video ? 'Shown once the video is being processed' : undefined} />
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        {video ? videoAxis : timeAxis}
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip {...TIP} labelFormatter={video ? videoLabel : clock} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="stepAfter" dataKey="tracked" name="Tracked people" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line type="stepAfter" dataKey="detected" name="All detections" stroke="#8b98a8" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

// Counting-line crossings per minute (IN up, OUT down from zero).
export function CrossingsChart({ stats, height = 200 }) {
  if (!stats) return <Empty height={height} />
  const data = stats.timeline.map((b) => ({ t: b.t, in: b.in, out: -b.out }))
  if (!stats.total_in && !stats.total_out) return <Empty height={height} text="No one has crossed a counting line yet" />
  const video = stats.axis === 'video'
  const label = video ? (t) => `${mmss(t)}–${mmss(t + stats.bucket_s)} in the video` : (t) => `${hm(t)} (${stats.bucket_min} min)`
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} stackOffset="sign" margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        <XAxis dataKey="t" tickFormatter={video ? mmss : hm} {...AXIS} minTickGap={24} />
        <YAxis allowDecimals={false} tickFormatter={(v) => Math.abs(v)} {...AXIS} />
        <Tooltip {...TIP} labelFormatter={label} formatter={(v, n) => [Math.abs(v), n]} cursor={{ fill: '#ffffff10' }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <ReferenceLine y={0} stroke="#8b98a8" />
        <Bar dataKey="in" name="IN" stackId="a" fill={IN_COLOR} isAnimationActive={false} />
        <Bar dataKey="out" name="OUT" stackId="a" fill={OUT_COLOR} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// How long people stayed in view (finished visits).
export function DwellHistogram({ stats, height = 200 }) {
  if (!stats) return <Empty height={height} />
  if (!stats.people) return <Empty height={height} text="Shown once people have left the view" />
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={stats.dwell_hist} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        <XAxis dataKey="label" {...AXIS} />
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip {...TIP} formatter={(v) => [v, 'People']} cursor={{ fill: '#ffffff10' }} />
        <Bar dataKey="count" name="People" fill={SERIES[0]} isAnimationActive={false} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// Live risk score of every zone, coloured by level, with the MEDIUM and HIGH lines.
export function RiskBars({ states, cameras, height }) {
  const data = cameras.flatMap((c) => (states[c.id]?.zones || []).map((z) => ({
    name: `${z.name} · ${c.name.split(' (')[0]}`, score: z.score, level: z.level,
  })))
  if (!data.length) return <Empty height={height || 120} text="No zones running yet" />
  return (
    <ResponsiveContainer width="100%" height={height || Math.max(120, 34 * data.length + 30)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        {GRID}
        <XAxis type="number" domain={[0, 100]} {...AXIS} />
        <YAxis type="category" dataKey="name" width={170} {...AXIS} />
        <Tooltip {...TIP} formatter={(v, _n, p) => [`${v} (${p.payload.level})`, 'Risk score']} cursor={{ fill: '#ffffff10' }} />
        <ReferenceLine x={35} stroke={LEVEL_COLOR.MEDIUM} strokeDasharray="2 4" />
        <ReferenceLine x={70} stroke={LEVEL_COLOR.HIGH} strokeDasharray="5 4" />
        <Bar dataKey="score" isAnimationActive={false} radius={[0, 4, 4, 0]}>
          {data.map((d) => <Cell key={d.name} fill={LEVEL_COLOR[d.level]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function LevelBars({ stats, height = 200 }) {
  if (!stats) return <Empty height={height} />
  const data = ['LOW', 'MEDIUM', 'HIGH'].map((l) => ({ level: l, count: stats.by_level[l] || 0 }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        <XAxis dataKey="level" {...AXIS} />
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip {...TIP} cursor={{ fill: '#ffffff10' }} />
        <Bar dataKey="count" name="Incidents (peak level)" isAnimationActive={false} radius={[4, 4, 0, 0]}>
          {data.map((d) => <Cell key={d.level} fill={LEVEL_COLOR[d.level]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function KindBars({ stats, height = 200 }) {
  if (!stats) return <Empty height={height} />
  const data = Object.entries(stats.by_kind).map(([k, n]) => ({ kind: KIND_LABEL[k] || k, count: n }))
  if (!data.length) return <Empty height={height} text="No incidents yet" />
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        <XAxis dataKey="kind" {...AXIS} interval={0} />
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip {...TIP} cursor={{ fill: '#ffffff10' }} />
        <Bar dataKey="count" name="Incidents" fill={SERIES[0]} isAnimationActive={false} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function TimelineBars({ stats, height = 200 }) {
  if (!stats) return <Empty height={height} />
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={stats.timeline} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        <XAxis dataKey="t" tickFormatter={hm} {...AXIS} minTickGap={24} />
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip {...TIP} labelFormatter={(t) => `From ${clock(t)} (${stats.bucket_min} min)`} cursor={{ fill: '#ffffff10' }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="MEDIUM" stackId="a" fill={LEVEL_COLOR.MEDIUM} isAnimationActive={false} />
        <Bar dataKey="HIGH" stackId="a" fill={LEVEL_COLOR.HIGH} isAnimationActive={false} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// Uploaded video: any per-second series on the video's own timeline.
// series: [{ key, name, color, dash, step }], where key is a field of the sample or a function of it.
export function VideoTimeChart({ samples, series, height = 200, unit = '', yDomain, refY }) {
  const data = (samples || []).map((s) => {
    const row = { t: s.vt }
    for (const ser of series) row[ser.name] = typeof ser.key === 'function' ? ser.key(s) : s[ser.key]
    return row
  })
  if (data.length < 2) return <Empty height={height} text="Shown once the video is being processed" />
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        {GRID}
        {videoAxis}
        <YAxis allowDecimals={!!unit} domain={yDomain} {...AXIS} />
        <Tooltip {...TIP} labelFormatter={videoLabel} formatter={(v, n) => [v == null ? '—' : `${v}${unit}`, n]} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {refY != null && <ReferenceLine y={refY.y} stroke="#8b98a8" strokeDasharray="4 3"
          label={{ value: refY.label, fill: '#8b98a8', fontSize: 10, position: 'insideTopRight' }} />}
        {series.map((ser, i) => (
          <Line key={ser.name} type={ser.step ? 'stepAfter' : 'monotone'} dataKey={ser.name} stroke={ser.color || SERIES[i % SERIES.length]}
            strokeWidth={2} strokeDasharray={ser.dash} dot={false} connectNulls isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
