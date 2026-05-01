import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import ProfileMenu from './ProfileMenu'

const items = [
  { k: 'Dashboard', to: '/' },
  { k: 'Matches', to: '/matches' },
  { k: 'Match', to: '/match/rma-mci' },
  { k: 'World Cup', to: '/world-cup' },
  { k: 'Model', to: '/model' },
  { k: 'Value', to: '/value' },
  { k: 'Pricing', to: '/pricing' },
  { k: 'About', to: '/about' },
]

export default function CCNav({ active, theme, onTheme, compact }) {
  const { isSignedIn } = useAuth()

  return (
    <nav
      style={{
        display: 'flex',
        gap: compact ? 12 : 18,
        alignItems: 'center',
        fontFamily: 'var(--cc-mono)',
        fontSize: compact ? 10 : 11,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
      }}
    >
      {items.map(({ k, to }) => (
        <Link
          key={k}
          to={to}
          style={{
            color: k === active ? 'var(--cc-text)' : 'var(--cc-muted)',
            textDecoration: 'none',
            borderBottom: k === active ? '1px solid var(--cc-gold)' : '1px solid transparent',
            paddingBottom: 2,
          }}
        >
          {k}
        </Link>
      ))}

      {/* Auth slot — replaces Sign-in link with the profile dropdown
          once the demo flag is set. */}
      {isSignedIn ? (
        <ProfileMenu />
      ) : (
        <Link
          to="/login"
          style={{
            color: 'var(--cc-text)',
            textDecoration: 'none',
            border: '1px solid var(--cc-line-strong)',
            borderRadius: 999,
            padding: '4px 12px',
            marginLeft: 4,
          }}
        >
          Sign in
        </Link>
      )}

      {onTheme && (
        <button
          type="button"
          onClick={() => onTheme(theme === 'night' ? 'day' : 'night')}
          style={{
            marginLeft: 8,
            background: 'none',
            border: '1px solid var(--cc-line-strong)',
            color: 'var(--cc-muted)',
            borderRadius: 999,
            padding: '4px 10px',
            cursor: 'pointer',
            fontFamily: 'inherit',
            fontSize: 'inherit',
            letterSpacing: 'inherit',
            textTransform: 'inherit',
          }}
        >
          {theme === 'night' ? '☾ Night' : '☀ Day'}
        </button>
      )}
    </nav>
  )
}
