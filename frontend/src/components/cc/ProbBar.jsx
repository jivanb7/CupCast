export default function ProbBar({ h, d, a, height = 10 }) {
  return (
    <div className="cc-probbar" style={{ height }}>
      <span className="h" style={{ flex: h }} />
      <span className="d" style={{ flex: d }} />
      <span className="a" style={{ flex: a }} />
    </div>
  )
}

export function ProbLegend({ h, d, a }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--cc-mono)', fontSize: 10, marginTop: 6 }}>
      <span className="tnum" style={{ color: 'var(--cc-green)' }}>{h}%</span>
      <span className="tnum" style={{ color: 'var(--cc-amber)' }}>{d}%</span>
      <span className="tnum" style={{ color: 'var(--cc-red)' }}>{a}%</span>
    </div>
  )
}
