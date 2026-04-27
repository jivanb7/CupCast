export default function DigitMorph({ value }) {
  const str = String(value)
  return (
    <span style={{ display: 'inline-flex' }}>
      {str.split('').map((c, i) => (
        <span
          key={i}
          style={{
            display: 'inline-block',
            overflow: 'hidden',
            height: '1em',
            position: 'relative',
            width: c === '1' ? '0.5em' : '0.6em',
            textAlign: 'center',
          }}
        >
          <span key={c} style={{ display: 'block', animation: 'cc-digit-up 250ms ease-out' }}>
            {c}
          </span>
        </span>
      ))}
    </span>
  )
}
