import ValueChip from './ValueChip'

export default function CardFooter({ pick, conf, value, edge }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingTop: 12,
        marginTop: 12,
        borderTop: '1px solid var(--cc-line)',
      }}
    >
      <span style={{ fontFamily: 'var(--cc-mono)', fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        <span style={{ color: 'var(--cc-muted)' }}>◆ Call</span>{' '}
        <span style={{ color: 'var(--cc-text)' }}>{pick}</span>{' '}
        <span className="tnum" style={{ color: 'var(--cc-muted)' }}>{conf}%</span>
      </span>
      {value && <ValueChip label={`◆ +${Number(edge).toFixed(1)}%`} />}
    </div>
  )
}
