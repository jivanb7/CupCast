export default function ValueChip({ label = '◆ VALUE' }) {
  return <span className="cc-value-chip">{label}</span>
}

export function CallChip({ team, conf, value }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontFamily: 'var(--cc-mono)',
        fontSize: 10,
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color: value ? 'var(--cc-gold)' : 'var(--cc-text)',
      }}
    >
      <span style={{ color: value ? 'var(--cc-gold)' : 'var(--cc-muted)' }}>◆ Call</span>
      <span>{team}</span>
      <span className="tnum" style={{ color: 'var(--cc-muted)' }}>{conf}%</span>
    </span>
  )
}
