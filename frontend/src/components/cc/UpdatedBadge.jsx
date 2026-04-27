export default function UpdatedBadge({ sec }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        fontFamily: 'var(--cc-mono)',
        fontSize: 10,
        color: 'var(--cc-muted)',
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
      }}
    >
      <span className="cc-live-dot" />
      <span>
        Updated <span style={{ color: 'var(--cc-text)' }} className="tnum">{sec}s</span> ago
      </span>
    </div>
  )
}
