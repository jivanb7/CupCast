/**
 * CountryFlag
 * Renders a country flag using the bundled flag-icons CSS sprite (lipis/flag-icons).
 * Falls back to a neutral dark placeholder when no code is supplied.
 */

const SIZES = {
  sm: { width: 16, height: 12 },
  md: { width: 24, height: 18 },
  lg: { width: 40, height: 30 },
}

export default function CountryFlag({
  code,
  size = 'md',
  rounded = true,
  className = '',
  title,
}) {
  const { width, height } = SIZES[size] || SIZES.md
  const radius = rounded ? '3px' : '0'

  const baseStyle = {
    width,
    height,
    display: 'inline-block',
    borderRadius: radius,
    overflow: 'hidden',
  }

  if (!code) {
    return (
      <span
        className={className}
        style={{ ...baseStyle, backgroundColor: '#1f2937' }}
        title={title}
        aria-label={title}
      />
    )
  }

  const normalized = String(code).toLowerCase()

  return (
    <span
      className={`fi fi-${normalized} fis ${className}`.trim()}
      style={baseStyle}
      title={title}
      aria-label={title}
    />
  )
}
