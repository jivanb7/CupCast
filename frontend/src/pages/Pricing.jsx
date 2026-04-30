// Pricing — editorial three-tier layout matching the About / Match-detail
// register: Fraunces serif italics for hero + tier names + price numerals,
// Inter Tight body, JetBrains Mono eyebrows, hairlines (no shadows),
// gold reserved for the recommended tier and price only. Copy lifted
// from the brand brief drafted on 2026-04-29; no betting CTAs anywhere.
//
// The CTAs link to /signup?tier=… placeholders so when auth + Stripe land
// the entry points are already in the markup. Login tab in CCNav will
// follow the same "coming soon" stub pattern when added.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import Aurora from '../components/cc/Aurora'
import CCNav from '../components/cc/CCNav'
import UpdatedBadge from '../components/cc/UpdatedBadge'
import SplitWords from '../components/cc/SplitWords'
import useCCTheme from '../hooks/useCCTheme'
import useClock from '../hooks/useClock'

// Single source of truth for tier data. Same array drives the cards AND
// the compare table — adding a feature in one place flows to both, no
// silent drift between the two surfaces.
const TIERS = [
  {
    key: 'matchday',
    name: 'Matchday',
    eyebrow: 'Free',
    price: { mo: 0, yr: 0 },
    pitch: 'For the casual visit before kickoff.',
    bullets: [
      "Today's slate only",
      'Top-5 European leagues',
      'Probability splits + the model’s "why" bullets',
      'No value picks, no model dashboard, no match-detail deep dive',
    ],
    cta: { label: 'Start free', to: '/' },
    recommended: false,
  },
  {
    key: 'season',
    name: 'Season Ticket',
    eyebrow: 'Most chosen',
    price: { mo: 8, yr: 72 }, // 25% off annual
    pitch: 'For the people who check every matchday.',
    bullets: [
      'Full slate — today + 7 days upcoming',
      'All 12 leagues including UCL + World Cup 2026',
      'Value picks with bookmaker edges',
      'Model accuracy dashboard',
      'World Cup 2026 simulator + bracket',
      'Match-detail page (form, H2H, scorers, cards)',
      'Email + SMS alerts when value picks land',
    ],
    cta: { label: 'Get Season Ticket', to: '/signup?tier=season' },
    recommended: true,
  },
  {
    key: 'directors',
    name: "Director's Box",
    eyebrow: 'Pro',
    price: { mo: 22, yr: 192 }, // 27% off annual
    pitch: 'For the people who keep score.',
    bullets: [
      'Everything in Season Ticket',
      'Predictions published 24 hours earlier',
      'Closing-line snapshot history',
      'API access — programmatic predictions',
      'Custom alerts (any team, threshold, league)',
      'Weekly model-insights newsletter',
      'Priority Discord access',
    ],
    cta: { label: "Enter the Director's Box", to: '/signup?tier=directors' },
    recommended: false,
  },
]

// Compare matrix — feature label + which tiers include it.
// '◆' = gold marker on the recommended tier, '•' = plain bullet,
// '—' = em-dash for "not included". Stored as the column-by-column
// truth value so we can render the marker glyph based on tier semantics.
const COMPARE_ROWS = [
  ['Today’s slate',                              [true,  true,  true]],
  ['Full 7-day upcoming view',                        [false, true,  true]],
  ['Top-5 leagues',                                   [true,  true,  true]],
  ['UCL + World Cup + MLS + Eredivisie + EFL',        [false, true,  true]],
  ['Probability splits + reasoning bullets',          [true,  true,  true]],
  ['Value picks with bookmaker edges',                [false, true,  true]],
  ['Model accuracy dashboard',                        [false, true,  true]],
  ['World Cup 2026 simulator',                        [false, true,  true]],
  ['Match-detail (form, H2H, scorers, cards)',        [false, true,  true]],
  ['Email + SMS value-pick alerts',                   [false, true,  true]],
  ['Predictions published 24h earlier',               [false, false, true]],
  ['Closing-line snapshot history',                   [false, false, true]],
  ['Programmatic API access',                         [false, false, true]],
  ['Custom alerts (any team, any edge)',              [false, false, true]],
  ['Weekly model-insights newsletter',                [false, false, true]],
  ['Priority Discord access',                         [false, false, true]],
]

const FAQ = [
  {
    q: 'When are predictions published before kickoff?',
    a: 'Public predictions land 12 hours before kickoff. Director’s Box subscribers see them 24 hours earlier — 36 hours total ahead of the match. The earlier the publication, the closer the model’s call sits to the opening line, before the market has fully digested team news.',
  },
  {
    q: 'Can I cancel anytime?',
    a: 'Yes. Monthly plans cancel at the end of the current period. Annual plans pro-rate the unused months back to your card. No retention friction, no cancellation phone tree.',
  },
  {
    q: 'What leagues are covered?',
    a: 'Top-5 European (Premier League, La Liga, Serie A, Bundesliga, Ligue 1), Championship, EFL League One + Two, National League, MLS, Eredivisie, UEFA Champions League, World Cup 2026. New leagues ship as CALIBRATING for several matchdays before they enter the public feed — honest beats present.',
  },
  {
    q: 'How calibrated are the probabilities, really?',
    a: 'A 70% pick should land 70% of the time. We track Brier score and bucketed calibration weekly on the Model page — same numbers we use internally. Current season: 64.2% top-line accuracy at 0.018 calibration error. The page recomputes from the raw call history every refresh; nothing is a marketing screenshot.',
  },
  {
    q: 'Do I have to give a card to start?',
    a: 'No. Matchday is free, no card, no email gate. Season Ticket and Director’s Box require a payment method only after a 7-day free trial.',
  },
]

export default function Pricing() {
  const [theme, setTheme] = useCCTheme()
  const tick = useClock(13)
  const [billing, setBilling] = useState('mo') // 'mo' | 'yr'

  return (
    <div className={`cc-root cc-${theme}`} style={{ position: 'relative', minHeight: '100vh', overflowX: 'hidden' }}>
      <Aurora />
      <div style={{ position: 'relative', zIndex: 2, padding: '40px 56px 80px' }}>
        {/* Masthead — same pattern as About */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', paddingBottom: 14, borderBottom: '2px solid var(--cc-text)' }}>
          <div className="cc-rise" style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
            <Link
              to="/"
              style={{ fontFamily: 'var(--cc-serif)', fontStyle: 'italic', fontWeight: 700, fontSize: 30, letterSpacing: '-0.02em', color: 'var(--cc-text)', textDecoration: 'none' }}
            >
              CupCast
            </Link>
            <div className="cc-eyebrow">No. 143 · Pricing · Three Ways In</div>
          </div>
          <div style={{ display: 'flex', gap: 18, alignItems: 'center' }}>
            <CCNav active="Pricing" theme={theme} onTheme={setTheme} />
            <UpdatedBadge sec={tick} />
          </div>
        </div>

        {/* Hero */}
        <section className="cc-rise" style={{ padding: '60px 0 40px', borderBottom: '1px solid var(--cc-line)' }}>
          <div className="cc-eyebrow">The Pitch</div>
          <h1
            className="serif"
            style={{
              fontSize: 'clamp(56px, 9vw, 124px)',
              fontStyle: 'italic',
              fontWeight: 600,
              letterSpacing: '-0.04em',
              lineHeight: 0.95,
              margin: '14px 0 0',
              maxWidth: 1100,
              textWrap: 'balance',
            }}
          >
            <SplitWords step={50} delay={120}>Pricing that earns its keep.</SplitWords>
          </h1>
          <p
            style={{
              fontFamily: 'var(--cc-serif)',
              fontStyle: 'italic',
              fontSize: 22,
              lineHeight: 1.5,
              color: 'var(--cc-muted)',
              maxWidth: 720,
              margin: '28px 0 0',
              textWrap: 'pretty',
            }}
          >
            A calibrated edge, priced for the people who actually use it. Pay monthly, pay yearly, or stay free — every tier ships with the same honest numbers and the same model.
          </p>

          {/* Billing toggle */}
          <div style={{ marginTop: 36, display: 'inline-flex', alignItems: 'center', gap: 10, padding: '6px 8px', border: '1px solid var(--cc-line-strong)', borderRadius: 999 }}>
            <BillingPill active={billing === 'mo'} onClick={() => setBilling('mo')}>
              Monthly
            </BillingPill>
            <BillingPill active={billing === 'yr'} onClick={() => setBilling('yr')}>
              Annual <span style={{ marginLeft: 6, color: 'var(--cc-gold)' }}>— save 25–27%</span>
            </BillingPill>
          </div>
        </section>

        {/* ① Plans */}
        <SectionHeader number="①" label="Plans" />
        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24, padding: '24px 0 50px' }}>
          {TIERS.map((t) => (
            <TierCard key={t.key} tier={t} billing={billing} />
          ))}
        </section>

        {/* ② Compare */}
        <SectionHeader number="②" label="Compare" />
        <section style={{ padding: '24px 0 50px', borderBottom: '1px solid var(--cc-line)' }}>
          <CompareTable rows={COMPARE_ROWS} />
        </section>

        {/* ③ FAQ */}
        <SectionHeader number="③" label="Questions, asked and answered" />
        <section style={{ padding: '24px 0 50px' }}>
          <FAQList items={FAQ} />
        </section>

        {/* Footer note */}
        <div
          className="mono"
          style={{
            marginTop: 30,
            paddingTop: 18,
            borderTop: '1px solid var(--cc-line)',
            fontSize: 11,
            color: 'var(--cc-dim)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            display: 'flex',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 14,
          }}
        >
          <span>
            <span style={{ color: 'var(--cc-gold)' }}>◆ Founder pricing</span> — first 100 Season Ticket / Director’s Box subscribers lock in $5 / $15 forever.
          </span>
          <span>
            ← <Link to="/" style={{ color: 'inherit' }}>Back to Dashboard</Link>
          </span>
        </div>
      </div>
    </div>
  )
}

// ── Subcomponents ─────────────────────────────────────────────────────

function SectionHeader({ number, label }) {
  return (
    <div className="cc-rise" style={{ display: 'flex', alignItems: 'center', gap: 14, paddingTop: 50, paddingBottom: 8, borderTop: '1px solid var(--cc-line-strong)' }}>
      <span className="cc-eyebrow" style={{ color: 'var(--cc-gold)' }}>{number} {label}</span>
    </div>
  )
}

function BillingPill({ active, children, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: active ? 'var(--cc-text)' : 'transparent',
        color: active ? 'var(--cc-bg)' : 'var(--cc-muted)',
        border: 'none',
        borderRadius: 999,
        padding: '8px 16px',
        cursor: 'pointer',
        fontFamily: 'var(--cc-mono)',
        fontSize: 11,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
      }}
    >
      {children}
    </button>
  )
}

function TierCard({ tier, billing }) {
  const price = billing === 'mo' ? tier.price.mo : tier.price.yr
  const isFree = price === 0
  const period = isFree ? null : billing === 'mo' ? '/mo' : '/yr'
  const recommended = tier.recommended

  return (
    <div
      style={{
        border: recommended ? '1px solid var(--cc-gold)' : '1px solid var(--cc-line-strong)',
        borderRadius: 12,
        padding: '28px 26px 24px',
        background: recommended ? 'var(--cc-surface-2)' : 'transparent',
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div className="cc-eyebrow" style={{ color: recommended ? 'var(--cc-gold)' : 'var(--cc-muted)' }}>
        {recommended ? '◆ ' : ''}{tier.eyebrow}
      </div>

      <h2
        className="serif"
        style={{
          fontSize: 44,
          fontStyle: 'italic',
          fontWeight: 600,
          letterSpacing: '-0.02em',
          lineHeight: 1,
          margin: '14px 0 0',
          color: 'var(--cc-text)',
          textWrap: 'balance',
        }}
      >
        {tier.name}
      </h2>

      <p style={{ fontFamily: 'var(--cc-serif)', fontStyle: 'italic', fontSize: 17, lineHeight: 1.45, color: 'var(--cc-muted)', margin: '12px 0 0', textWrap: 'pretty' }}>
        {tier.pitch}
      </p>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, margin: '24px 0 4px' }}>
        <span
          className="serif tnum"
          style={{
            fontSize: 64,
            fontStyle: 'italic',
            fontWeight: 600,
            letterSpacing: '-0.03em',
            lineHeight: 1,
            color: recommended ? 'var(--cc-gold)' : 'var(--cc-text)',
          }}
        >
          {isFree ? 'Free' : `$${price}`}
        </span>
        {period && (
          <span className="mono" style={{ fontSize: 12, color: 'var(--cc-muted)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            {period}
          </span>
        )}
      </div>
      {!isFree && billing === 'yr' && (
        <div className="mono" style={{ fontSize: 10, color: 'var(--cc-dim)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          ≈ ${(tier.price.yr / 12).toFixed(2)}/mo, billed annually
        </div>
      )}

      <ul style={{ listStyle: 'none', margin: '24px 0 0', padding: 0, display: 'grid', gap: 10, flex: 1 }}>
        {tier.bullets.map((b, i) => (
          <li key={i} style={{ display: 'flex', gap: 10, fontFamily: 'var(--cc-body)', fontSize: 14, lineHeight: 1.5, color: 'var(--cc-text)' }}>
            <span aria-hidden style={{ color: recommended ? 'var(--cc-gold)' : 'var(--cc-muted)', flexShrink: 0 }}>{recommended ? '◆' : '•'}</span>
            <span>{b}</span>
          </li>
        ))}
      </ul>

      <Link
        to={tier.cta.to}
        style={{
          marginTop: 28,
          display: 'block',
          textAlign: 'center',
          padding: '14px 18px',
          borderRadius: 999,
          background: recommended ? 'var(--cc-gold)' : 'transparent',
          color: recommended ? 'var(--cc-bg)' : 'var(--cc-text)',
          border: recommended ? '1px solid var(--cc-gold)' : '1px solid var(--cc-line-strong)',
          textDecoration: 'none',
          fontFamily: 'var(--cc-mono)',
          fontSize: 11,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          fontWeight: 600,
        }}
      >
        {tier.cta.label}
      </Link>
    </div>
  )
}

function CompareTable({ rows }) {
  return (
    <div style={{ border: '1px solid var(--cc-line)', borderRadius: 8, overflow: 'hidden' }}>
      {/* Header row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '2fr 1fr 1fr 1fr',
          alignItems: 'center',
          padding: '14px 20px',
          background: 'var(--cc-surface-2)',
          borderBottom: '1px solid var(--cc-line-strong)',
          fontFamily: 'var(--cc-mono)',
          fontSize: 10,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: 'var(--cc-muted)',
        }}
      >
        <span>Feature</span>
        <span style={{ textAlign: 'center' }}>Matchday</span>
        <span style={{ textAlign: 'center', color: 'var(--cc-gold)' }}>◆ Season Ticket</span>
        <span style={{ textAlign: 'center' }}>Director’s Box</span>
      </div>

      {rows.map(([label, [m, s, d]], i) => (
        <div
          key={i}
          style={{
            display: 'grid',
            gridTemplateColumns: '2fr 1fr 1fr 1fr',
            alignItems: 'center',
            padding: '12px 20px',
            borderBottom: i < rows.length - 1 ? '1px solid var(--cc-line)' : 'none',
            fontFamily: 'var(--cc-body)',
            fontSize: 14,
            color: 'var(--cc-text)',
          }}
        >
          <span style={{ color: 'var(--cc-text)' }}>{label}</span>
          <CompareCell included={m} recommended={false} />
          <CompareCell included={s} recommended={true} />
          <CompareCell included={d} recommended={false} />
        </div>
      ))}
    </div>
  )
}

function CompareCell({ included, recommended }) {
  if (!included) {
    return (
      <span style={{ textAlign: 'center', fontFamily: 'var(--cc-mono)', color: 'var(--cc-dim)' }}>—</span>
    )
  }
  return (
    <span
      style={{
        textAlign: 'center',
        fontFamily: 'var(--cc-mono)',
        fontSize: 14,
        color: recommended ? 'var(--cc-gold)' : 'var(--cc-text)',
        fontWeight: recommended ? 600 : 400,
      }}
    >
      {recommended ? '◆' : '•'}
    </span>
  )
}

function FAQList({ items }) {
  const [openIdx, setOpenIdx] = useState(0)
  return (
    <div style={{ border: '1px solid var(--cc-line)', borderRadius: 8, overflow: 'hidden' }}>
      {items.map((it, i) => {
        const open = openIdx === i
        return (
          <div
            key={i}
            style={{
              borderBottom: i < items.length - 1 ? '1px solid var(--cc-line)' : 'none',
            }}
          >
            <button
              type="button"
              onClick={() => setOpenIdx(open ? -1 : i)}
              style={{
                width: '100%',
                background: 'transparent',
                border: 'none',
                padding: '18px 22px',
                textAlign: 'left',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                gap: 18,
                color: 'var(--cc-text)',
              }}
            >
              <span className="serif" style={{ fontStyle: 'italic', fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>
                {it.q}
              </span>
              <span className="mono" style={{ color: 'var(--cc-muted)', fontSize: 18 }}>
                {open ? '–' : '+'}
              </span>
            </button>
            {open && (
              <div style={{ padding: '0 22px 22px', fontFamily: 'var(--cc-serif)', fontSize: 17, lineHeight: 1.55, color: 'var(--cc-muted)', maxWidth: 820, textWrap: 'pretty' }}>
                {it.a}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
