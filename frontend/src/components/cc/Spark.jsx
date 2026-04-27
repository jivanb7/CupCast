export default function Spark({ data, w = 120, h = 30, color = 'var(--cc-gold)' }) {
  if (!data || data.length === 0) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const pts = data.map((v, i) => {
    const x = (i / Math.max(1, data.length - 1)) * w
    const y = h - ((v - min) / Math.max(1, max - min)) * h
    return [x, y]
  })
  const path = pts.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(' ')
  const last = pts[pts.length - 1]
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: w, height: h, display: 'block' }}>
      <path d={path} fill="none" stroke={color} strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="2.2" fill={color} />
    </svg>
  )
}
