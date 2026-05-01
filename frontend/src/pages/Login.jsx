/* Login / Sign-up — façade auth page for the demo.
 *
 * Email + password fields and Google/Apple buttons are decorative. The
 * only button that does anything is "Try the demo" — it sets the
 * localStorage flag via AuthContext and routes to the dashboard.
 *
 * Submitting the form shows a small inline note instead of an alert or
 * silent failure, so the form feels responsive without pretending to
 * authenticate.
 */

import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import Aurora from '../components/cc/Aurora'
import SplitWords from '../components/cc/SplitWords'
import useCCTheme from '../hooks/useCCTheme'
import { useAuth } from '../context/AuthContext'

export default function Login() {
  const [theme, setTheme] = useCCTheme()
  const { isSignedIn, signInAsDemo } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [mode, setMode] = useState('signup') // 'signin' | 'signup' — default to signup for new visitors
  const [showDemoNote, setShowDemoNote] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  // Already signed in (e.g. they navigated here manually) → bounce home.
  if (isSignedIn) {
    const dest = location.state?.from?.pathname || '/'
    return <Navigate to={dest} replace />
  }

  function onSubmit(e) {
    e.preventDefault()
    setShowDemoNote(true)
  }

  function onDemo() {
    signInAsDemo()
    navigate('/', { replace: true })
  }

  return (
    <div className={`cc-root cc-${theme}`} style={{ position: 'relative', minHeight: '100vh', overflowX: 'hidden' }}>
      <Aurora />

      {/* Top bar — minimal. CupCast wordmark + theme toggle. No nav,
          because there's nothing to navigate to before signing in. */}
      <div
        style={{
          position: 'relative',
          zIndex: 2,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '32px 48px 0',
        }}
      >
        <Link
          to="/login"
          style={{
            fontFamily: 'var(--cc-serif)',
            fontStyle: 'italic',
            fontWeight: 700,
            fontSize: 28,
            letterSpacing: '-0.02em',
            color: 'var(--cc-text)',
            textDecoration: 'none',
          }}
        >
          CupCast
        </Link>
        <button
          type="button"
          onClick={() => setTheme(theme === 'night' ? 'day' : 'night')}
          style={{
            background: 'none',
            border: '1px solid var(--cc-line-strong)',
            color: 'var(--cc-muted)',
            borderRadius: 999,
            padding: '6px 14px',
            cursor: 'pointer',
            fontFamily: 'var(--cc-mono)',
            fontSize: 11,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
          }}
        >
          {theme === 'night' ? '☾ Night' : '☀ Day'}
        </button>
      </div>

      {/* Centered card */}
      <main
        style={{
          position: 'relative',
          zIndex: 2,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '60px 24px 80px',
          minHeight: 'calc(100vh - 100px)',
        }}
      >
        {/* Editorial hero line */}
        <div className="cc-eyebrow" style={{ color: 'var(--cc-gold)', marginBottom: 14 }}>
          ◆ The Front Door
        </div>
        <h1
          className="serif"
          style={{
            fontSize: 'clamp(40px, 6vw, 72px)',
            fontStyle: 'italic',
            fontWeight: 600,
            letterSpacing: '-0.03em',
            lineHeight: 1,
            margin: 0,
            textAlign: 'center',
            maxWidth: 640,
            textWrap: 'balance',
          }}
        >
          <SplitWords step={50} delay={120}>
            {mode === 'signin' ? 'Welcome back to CupCast.' : 'Make yourself at home.'}
          </SplitWords>
        </h1>
        <p
          style={{
            fontFamily: 'var(--cc-serif)',
            fontStyle: 'italic',
            fontSize: 18,
            lineHeight: 1.5,
            color: 'var(--cc-muted)',
            textAlign: 'center',
            maxWidth: 540,
            margin: '20px 0 0',
            textWrap: 'pretty',
          }}
        >
          {mode === 'signin'
            ? 'Sign in to pick up where you left off, or try the demo to skip ahead.'
            : 'Create an account, or skip the form and try the demo straight away.'}
        </p>

        {/* Auth card */}
        <section
          style={{
            marginTop: 44,
            width: '100%',
            maxWidth: 420,
            border: '1px solid var(--cc-line-strong)',
            borderRadius: 12,
            padding: '28px 28px 24px',
            background: 'var(--cc-surface)',
          }}
        >
          {/* OAuth buttons (decorative) */}
          <div style={{ display: 'grid', gap: 10 }}>
            <OAuthButton onClick={() => setShowDemoNote(true)} label="Continue with Google" glyph="G" />
            <OAuthButton onClick={() => setShowDemoNote(true)} label="Continue with Apple"  glyph=""/>
          </div>

          {/* Divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '22px 0 18px' }}>
            <span style={{ flex: 1, height: 1, background: 'var(--cc-line)' }} />
            <span className="mono" style={{ fontSize: 10, color: 'var(--cc-dim)', letterSpacing: '0.16em', textTransform: 'uppercase' }}>
              or with email
            </span>
            <span style={{ flex: 1, height: 1, background: 'var(--cc-line)' }} />
          </div>

          {/* Form */}
          <form onSubmit={onSubmit} style={{ display: 'grid', gap: 12 }}>
            <Field
              label="Email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setShowDemoNote(false) }}
              placeholder="you@example.com"
              required
            />
            <Field
              label="Password"
              type="password"
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => { setPassword(e.target.value); setShowDemoNote(false) }}
              placeholder="••••••••"
              required
            />

            <button
              type="submit"
              style={{
                marginTop: 6,
                padding: '13px 16px',
                borderRadius: 8,
                border: '1px solid var(--cc-line-strong)',
                background: 'transparent',
                color: 'var(--cc-text)',
                fontFamily: 'var(--cc-display)',
                fontWeight: 500,
                fontSize: 14,
                letterSpacing: '-0.005em',
                cursor: 'pointer',
              }}
            >
              {mode === 'signin' ? 'Sign in' : 'Create account'}
            </button>

            {showDemoNote && (
              <div
                className="mono"
                style={{
                  fontSize: 10,
                  color: 'var(--cc-gold)',
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  textAlign: 'center',
                  padding: '4px 0',
                }}
              >
                ◆ Demo mode — use the demo button below
              </div>
            )}
          </form>

          {/* Mode toggle */}
          <div
            style={{
              marginTop: 18,
              fontFamily: 'var(--cc-display)',
              fontSize: 13,
              color: 'var(--cc-muted)',
              textAlign: 'center',
            }}
          >
            {mode === 'signin' ? (
              <>
                New to CupCast?{' '}
                <button
                  type="button"
                  onClick={() => { setMode('signup'); setShowDemoNote(false) }}
                  style={linkButton}
                >
                  Create an account
                </button>
              </>
            ) : (
              <>
                Already have an account?{' '}
                <button
                  type="button"
                  onClick={() => { setMode('signin'); setShowDemoNote(false) }}
                  style={linkButton}
                >
                  Sign in
                </button>
              </>
            )}
          </div>
        </section>

        {/* Demo button — the actual entry point */}
        <div style={{ marginTop: 28, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
          <button
            type="button"
            onClick={onDemo}
            style={{
              padding: '14px 28px',
              borderRadius: 999,
              background: 'var(--cc-gold)',
              border: '1px solid var(--cc-gold)',
              color: '#0E1223',
              fontFamily: 'var(--cc-mono)',
              fontWeight: 600,
              fontSize: 12,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              cursor: 'pointer',
            }}
          >
            ◆ Try the demo →
          </button>
          <span
            className="mono"
            style={{
              fontSize: 10,
              color: 'var(--cc-dim)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
            }}
          >
            One click — no email, no card. Loads as a Season Ticket holder.
          </span>
        </div>

        {/* Pricing peek footer */}
        <div
          style={{
            marginTop: 60,
            fontFamily: 'var(--cc-display)',
            fontSize: 14,
            color: 'var(--cc-muted)',
            textAlign: 'center',
          }}
        >
          Curious about the plans?{' '}
          <Link to="/pricing" style={{ color: 'var(--cc-gold)', textDecoration: 'underline', fontWeight: 500 }}>
            See pricing
          </Link>
        </div>
      </main>
    </div>
  )
}

// ── Subcomponents ─────────────────────────────────────────────────────

const linkButton = {
  background: 'none',
  border: 0,
  padding: 0,
  color: 'var(--cc-gold)',
  cursor: 'pointer',
  font: 'inherit',
  textDecoration: 'underline',
}

function OAuthButton({ label, glyph, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        padding: '12px 14px',
        borderRadius: 8,
        background: 'transparent',
        border: '1px solid var(--cc-line-strong)',
        color: 'var(--cc-text)',
        fontFamily: 'var(--cc-display)',
        fontSize: 14,
        fontWeight: 500,
        cursor: 'pointer',
      }}
    >
      <span
        aria-hidden
        className="mono"
        style={{
          width: 20,
          textAlign: 'center',
          color: 'var(--cc-muted)',
          fontSize: 14,
        }}
      >
        {glyph}
      </span>
      {label}
    </button>
  )
}

function Field({ label, ...inputProps }) {
  return (
    <label style={{ display: 'grid', gap: 6 }}>
      <span
        className="mono"
        style={{ fontSize: 10, color: 'var(--cc-muted)', letterSpacing: '0.14em', textTransform: 'uppercase' }}
      >
        {label}
      </span>
      <input
        {...inputProps}
        style={{
          padding: '12px 14px',
          borderRadius: 8,
          border: '1px solid var(--cc-line-strong)',
          background: 'transparent',
          color: 'var(--cc-text)',
          fontFamily: 'var(--cc-display)',
          fontSize: 14,
          outline: 'none',
        }}
      />
    </label>
  )
}
