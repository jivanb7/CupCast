export default function SplitWords({ children, delay = 200, step = 40, className, style }) {
  const text = String(children ?? '')
  const words = text.split(' ')
  return (
    <span className={className} style={style}>
      {words.map((w, i) => (
        <span key={i} style={{ display: 'inline-block', overflow: 'hidden' }}>
          <span
            style={{
              display: 'inline-block',
              animation: `cc-word-rise 600ms cubic-bezier(.2,.7,.2,1) ${delay + i * step}ms both`,
            }}
          >
            {w}
            {i < words.length - 1 ? '\u00A0' : ''}
          </span>
        </span>
      ))}
    </span>
  )
}
