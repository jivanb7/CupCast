import useCountUp from '../../hooks/useCountUp'
import Eyebrow from './Eyebrow'

export default function HDACell({ label, val, color, highlight, sub, big }) {
  const v = useCountUp(val, { duration: 700 })
  const intV = Math.round(v)
  return (
    <div
      style={{
        padding: big ? '32px 28px' : '24px 22px',
        position: 'relative',
        borderRight: '1px solid var(--cc-line)',
        background: highlight ? 'rgba(245,158,11,0.04)' : 'transparent',
        flex: 1,
      }}
    >
      <Eyebrow>{label}</Eyebrow>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 10 }}>
        <span
          className="serif tnum"
          style={{
            fontSize: big ? 92 : 64,
            fontStyle: 'italic',
            fontWeight: 600,
            color: highlight ? 'var(--cc-gold)' : 'var(--cc-text)',
            letterSpacing: '-0.04em',
            lineHeight: 0.9,
          }}
        >
          {intV}
        </span>
        <span className="serif" style={{ fontSize: big ? 36 : 24, color: 'var(--cc-muted)', fontStyle: 'italic' }}>
          %
        </span>
      </div>
      <div
        style={{
          marginTop: 14,
          height: 3,
          background: color,
          width: `${Math.max(0, Math.min(100, intV))}%`,
          transition: 'width 700ms cubic-bezier(.2,.7,.2,1)',
        }}
      />
      {sub && (
        <div
          style={{
            marginTop: 8,
            fontFamily: 'var(--cc-mono)',
            fontSize: 10,
            color: 'var(--cc-muted)',
            letterSpacing: '0.1em',
          }}
        >
          {sub}
        </div>
      )}
    </div>
  )
}
