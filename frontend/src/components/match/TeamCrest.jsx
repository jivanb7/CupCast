import { useState } from 'react'
import CountryFlag from '../ui/CountryFlag'

/**
 * TeamCrest — circular team crest with graceful fallbacks.
 *
 * Render priority:
 *   1. <img src={crestUrl}> if provided AND loads successfully
 *   2. <CountryFlag /> styled as a circle (national teams)
 *   3. Initials badge (first 2 chars of name) with deterministic
 *      colors derived from the name when {colors} is omitted
 */

const SIZE_PX = {
  xs: 24,
  sm: 32,
  md: 48,
  lg: 72,
  xl: 96,
}

const FONT_SIZE_PX = {
  xs: 9,
  sm: 11,
  md: 14,
  lg: 22,
  xl: 30,
}

// Deterministic colors hashed from team name. Stable across renders.
// Football-themed kit-inspired palette: rich, saturated, intentional.
const FALLBACK_PALETTES = [
  { bg: '#dc2626', fg: '#ffffff' }, // red / white
  { bg: '#1e40af', fg: '#fbbf24' }, // navy / gold
  { bg: '#065f46', fg: '#ffffff' }, // forest green / white
  { bg: '#7c2d12', fg: '#fed7aa' }, // maroon / cream
  { bg: '#374151', fg: '#ffffff' }, // slate / white
  { bg: '#0e7490', fg: '#ffffff' }, // teal / white
  { bg: '#7c3aed', fg: '#fef3c7' }, // purple / cream
  { bg: '#fbbf24', fg: '#1e3a8a' }, // gold / navy
]

function hashName(name) {
  let h = 0
  for (let i = 0; i < name.length; i += 1) {
    h = (h * 31 + name.charCodeAt(i)) >>> 0
  }
  return h
}

function paletteFor(name) {
  return FALLBACK_PALETTES[hashName(name) % FALLBACK_PALETTES.length]
}

// Darken a hex color (#rrggbb) by a percent (0-1). Used to build the gradient.
function darkenHex(hex, amount = 0.18) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)
  if (!m) return hex
  const factor = 1 - amount
  const r = Math.max(0, Math.min(255, Math.round(parseInt(m[1], 16) * factor)))
  const g = Math.max(0, Math.min(255, Math.round(parseInt(m[2], 16) * factor)))
  const b = Math.max(0, Math.min(255, Math.round(parseInt(m[3], 16) * factor)))
  const toHex = (v) => v.toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

function initialsFor(name) {
  const parts = String(name).trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export default function TeamCrest({
  name,
  crestUrl,
  countryCode,
  colors,
  size = 'md',
  className = '',
}) {
  const [imgFailed, setImgFailed] = useState(false)
  const px = SIZE_PX[size] ?? SIZE_PX.md
  const fontPx = FONT_SIZE_PX[size] ?? FONT_SIZE_PX.md

  const baseStyle = {
    width: px,
    height: px,
    borderRadius: '50%',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    overflow: 'hidden',
    border: '1px solid rgba(255,255,255,0.08)',
  }

  if (crestUrl && !imgFailed) {
    return (
      <span style={baseStyle} className={className} aria-label={name}>
        <img
          src={crestUrl}
          alt=""
          width={px}
          height={px}
          loading="lazy"
          onError={() => setImgFailed(true)}
          style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#0b1220' }}
        />
      </span>
    )
  }

  if (countryCode) {
    // Render flag clipped into the circle. flag-icons uses a background-image,
    // so we wrap and stretch it.
    return (
      <span
        style={{ ...baseStyle, background: '#0b1220' }}
        className={className}
        aria-label={name}
        title={name}
      >
        <CountryFlag
          code={countryCode}
          size="lg"
          rounded={false}
          className=""
        />
      </span>
    )
  }

  const palette = colors || paletteFor(String(name || ''))
  const bgDark = darkenHex(palette.bg, 0.18)
  // Inset ring: a subtle lighter top-edge highlight + darker bottom shadow.
  // Layered box-shadow gives a designed "kit-button" depth without looking gaudy.
  const insetRing = [
    'inset 0 1px 0 rgba(255,255,255,0.14)',
    'inset 0 -1px 0 rgba(0,0,0,0.18)',
    'inset 0 0 0 1px rgba(255,255,255,0.05)',
  ].join(', ')

  return (
    <span
      style={{
        ...baseStyle,
        // Override the generic baseStyle border — the inset ring handles edge depth.
        border: '1px solid rgba(0,0,0,0.25)',
        background: `linear-gradient(135deg, ${palette.bg} 0%, ${bgDark} 100%)`,
        color: palette.fg,
        fontWeight: 800,
        fontSize: fontPx,
        letterSpacing: '-0.02em',
        textShadow: '0 1px 0 rgba(0,0,0,0.18)',
        boxShadow: insetRing,
        // Use a font stack tuned for tight initials.
        fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
        lineHeight: 1,
        userSelect: 'none',
      }}
      className={className}
      aria-label={name}
      title={name}
    >
      {initialsFor(name || '?')}
    </span>
  )
}
