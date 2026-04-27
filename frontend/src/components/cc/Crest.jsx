import { useState } from 'react'

// Renders a real club crest image when `crestUrl` is provided, with the
// short-code colored disk as a graceful fallback during load and on error.
// Keeps the component a single import-shape for every page that uses it.
export default function Crest({ short, color, size = 32, dim, crestUrl, alt }) {
  const [errored, setErrored] = useState(false)
  const showImage = Boolean(crestUrl) && !errored
  const baseStyle = {
    width: size,
    height: size,
    fontSize: Math.max(8, size * 0.32),
    background: dim ? 'var(--cc-surface-2)' : color || 'var(--cc-surface-2)',
    color: dim ? 'var(--cc-muted)' : '#0E1223',
    border: '1px solid var(--cc-line-strong)',
    overflow: 'hidden',
  }
  if (showImage) {
    return (
      <div className="cc-crest" style={{ ...baseStyle, padding: 2, background: 'var(--cc-surface)' }}>
        <img
          src={crestUrl}
          alt={alt || short || ''}
          width={size - 4}
          height={size - 4}
          loading="lazy"
          onError={() => setErrored(true)}
          style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
        />
      </div>
    )
  }
  return (
    <div className="cc-crest" style={baseStyle}>
      {short}
    </div>
  )
}
