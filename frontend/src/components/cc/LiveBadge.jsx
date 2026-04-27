import DigitMorph from './DigitMorph'

export default function LiveBadge({ minute, big }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className="cc-live-dot" />
      <span
        className="mono tnum"
        style={{
          fontSize: big ? 12 : 10,
          color: 'var(--cc-green)',
          letterSpacing: '0.1em',
          display: 'inline-flex',
          alignItems: 'baseline',
        }}
      >
        LIVE&nbsp;<DigitMorph value={minute} />&apos;
      </span>
    </span>
  )
}
