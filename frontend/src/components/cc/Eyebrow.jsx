export default function Eyebrow({ children, gold, style }) {
  return (
    <div className="cc-eyebrow" style={{ color: gold ? 'var(--cc-gold)' : undefined, ...style }}>
      {children}
    </div>
  )
}
