/* Billing — stub for the demo's "Manage subscription" link.
 *
 * Pricing-page Season Ticket card (when signed in) and the profile
 * dropdown both link here. A real product would route to the Stripe
 * Customer Portal; the demo just shows a placeholder so the click does
 * something rather than 404.
 */

import { Link } from 'react-router-dom'
import Aurora from '../components/cc/Aurora'
import CCNav from '../components/cc/CCNav'
import UpdatedBadge from '../components/cc/UpdatedBadge'
import useCCTheme from '../hooks/useCCTheme'
import useClock from '../hooks/useClock'

export default function Billing() {
  const [theme, setTheme] = useCCTheme()
  const tick = useClock(7)

  return (
    <div className={`cc-root cc-${theme}`} style={{ position: 'relative', minHeight: '100vh', overflowX: 'hidden' }}>
      <Aurora />
      <div style={{ position: 'relative', zIndex: 2, padding: '40px 56px 80px' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-end',
            paddingBottom: 14,
            borderBottom: '2px solid var(--cc-text)',
          }}
        >
          <div className="cc-rise" style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
            <Link
              to="/"
              style={{
                fontFamily: 'var(--cc-serif)',
                fontStyle: 'italic',
                fontWeight: 700,
                fontSize: 30,
                letterSpacing: '-0.02em',
                color: 'var(--cc-text)',
                textDecoration: 'none',
              }}
            >
              CupCast
            </Link>
            <div className="cc-eyebrow">No. 144 · Billing · Account</div>
          </div>
          <div style={{ display: 'flex', gap: 18, alignItems: 'center' }}>
            <CCNav theme={theme} onTheme={setTheme} />
            <UpdatedBadge sec={tick} />
          </div>
        </div>

        <section
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '120px 24px 80px',
            textAlign: 'center',
            gap: 18,
          }}
        >
          <div className="cc-eyebrow" style={{ color: 'var(--cc-gold)' }}>
            ◆ Subscription management
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
              maxWidth: 720,
              textWrap: 'balance',
            }}
          >
            Coming soon.
          </h1>
          <p
            style={{
              fontFamily: 'var(--cc-serif)',
              fontStyle: 'italic',
              fontSize: 19,
              lineHeight: 1.55,
              color: 'var(--cc-muted)',
              maxWidth: 540,
              margin: '6px 0 0',
              textWrap: 'pretty',
            }}
          >
            Account management, billing history, and subscription changes will live
            here once paid plans launch. For now, your demo account is on{' '}
            <span style={{ color: 'var(--cc-gold)' }}>Season Ticket</span> at no
            charge.
          </p>

          <Link
            to="/pricing"
            style={{
              marginTop: 28,
              padding: '12px 24px',
              borderRadius: 999,
              border: '1px solid var(--cc-line-strong)',
              color: 'var(--cc-text)',
              fontFamily: 'var(--cc-mono)',
              fontSize: 11,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              textDecoration: 'none',
            }}
          >
            ← Back to pricing
          </Link>
        </section>
      </div>
    </div>
  )
}
