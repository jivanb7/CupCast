/* ProfileMenu — nav-bar profile button + dropdown for the demo.
 *
 * Renders nothing if logged out (CCNav shows a "Sign in" link instead).
 * When logged in, shows an initial-avatar + tier badge that opens a small
 * dropdown with the user's email, current tier, a Manage-subscription
 * link, and a Sign-out (demo) action that clears the localStorage flag.
 *
 * Click-outside-to-close handled with a backdrop element rather than a
 * document listener so it composes cleanly with the dark/light themes.
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

export default function ProfileMenu() {
  const { isSignedIn, user, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()

  if (!isSignedIn || !user) return null

  function handleSignOut() {
    setOpen(false)
    signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((s) => !s)}
        aria-haspopup="menu"
        aria-expanded={open}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 10,
          padding: '4px 12px 4px 4px',
          borderRadius: 999,
          background: 'transparent',
          border: '1px solid var(--cc-line-strong)',
          color: 'var(--cc-muted)',
          cursor: 'pointer',
          fontFamily: 'var(--cc-mono)',
          fontSize: 10,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}
      >
        <span
          aria-hidden
          style={{
            width: 24,
            height: 24,
            borderRadius: '50%',
            background: 'var(--cc-gold)',
            color: '#0E1223',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--cc-mono)',
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {user.initial}
        </span>
        <span style={{ color: 'var(--cc-gold)' }}>◆ {user.tierLabel}</span>
        <span aria-hidden style={{ color: 'var(--cc-dim)', marginLeft: 2 }}>▾</span>
      </button>

      {open && (
        <>
          {/* Backdrop — click anywhere to close. */}
          <div
            onClick={() => setOpen(false)}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 100,
              background: 'transparent',
            }}
          />
          {/* Dropdown */}
          <div
            role="menu"
            style={{
              position: 'absolute',
              top: 'calc(100% + 8px)',
              right: 0,
              zIndex: 101,
              minWidth: 240,
              background: 'var(--cc-surface)',
              border: '1px solid var(--cc-line-strong)',
              borderRadius: 10,
              padding: '12px 0 8px',
              fontFamily: 'var(--cc-display)',
            }}
          >
            <div style={{ padding: '4px 16px 12px', borderBottom: '1px solid var(--cc-line)' }}>
              <div style={{ fontSize: 13, color: 'var(--cc-text)' }}>{user.email}</div>
              <div
                className="mono"
                style={{
                  marginTop: 4,
                  fontSize: 10,
                  color: 'var(--cc-gold)',
                  letterSpacing: '0.14em',
                  textTransform: 'uppercase',
                }}
              >
                ◆ {user.tierLabel}
              </div>
            </div>

            <div style={{ padding: '6px 0' }}>
              <MenuLink to="/billing" onClick={() => setOpen(false)}>
                Manage subscription
              </MenuLink>
              <MenuLink to="/pricing" onClick={() => setOpen(false)}>
                See plans
              </MenuLink>
            </div>

            <div style={{ borderTop: '1px solid var(--cc-line)', padding: '6px 0' }}>
              <MenuButton onClick={handleSignOut}>Sign out (demo)</MenuButton>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

const itemStyle = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  padding: '10px 16px',
  background: 'transparent',
  border: 'none',
  color: 'var(--cc-text)',
  fontSize: 13,
  fontFamily: 'inherit',
  textDecoration: 'none',
  cursor: 'pointer',
}

function MenuLink({ to, children, onClick }) {
  return (
    <Link to={to} onClick={onClick} style={itemStyle} role="menuitem">
      {children}
    </Link>
  )
}

function MenuButton({ children, onClick }) {
  return (
    <button type="button" onClick={onClick} style={itemStyle} role="menuitem">
      {children}
    </button>
  )
}
