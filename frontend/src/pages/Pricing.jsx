// Pricing — three-tier page rendered against the visual contract Claude
// Design produced in design_handoff_cupcast/design_handoff_cupcast_price/
// pricing.html. The .pr-* class system (cut-through "MOST CHOSEN" badge,
// hover lift on cards, rotating "+→×" FAQ marker, hairline-only table)
// lives in src/styles/pricing.css; this file just renders the markup the
// stylesheet expects.
//
// Design Files only contained pricing.html + the unmodified cc-shared.css
// + cc-ui.jsx — the corresponding pricing.jsx never finished generating
// before the EndStreamResponse error killed it. This component fills that
// gap; the visual outcome should match what Claude Design intended.

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Aurora from '../components/cc/Aurora'
import CCNav from '../components/cc/CCNav'
import UpdatedBadge from '../components/cc/UpdatedBadge'
import SplitWords from '../components/cc/SplitWords'
import useCCTheme from '../hooks/useCCTheme'
import useClock from '../hooks/useClock'
import { useAuth } from '../context/AuthContext'

// Tier ordering — used to decide whether a given card is the user's
// current plan, an upgrade, or a downgrade.
const TIER_ORDER = { matchday: 0, season: 1, directors: 2 }

// Tier data — single source of truth for the cards AND the compare table.
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
    price: { mo: 8, yr: 72 }, // ≈25% off annual
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
    price: { mo: 22, yr: 192 }, // ≈27% off annual
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

// Compare matrix — feature row + boolean per tier.
// Marker glyph rendered as • on plain tiers, ◆ on the recommended tier,
// — on tiers that don't include the feature.
const COMPARE_ROWS = [
  ["Today’s slate",                                [true,  true,  true]],
  ['Full 7-day upcoming view',                          [false, true,  true]],
  ['Top-5 leagues',                                     [true,  true,  true]],
  ['UCL + World Cup + MLS + Eredivisie + EFL',          [false, true,  true]],
  ['Probability splits + reasoning bullets',            [true,  true,  true]],
  ['Value picks with bookmaker edges',                  [false, true,  true]],
  ['Model accuracy dashboard',                          [false, true,  true]],
  ['World Cup 2026 simulator',                          [false, true,  true]],
  ['Match-detail (form, H2H, scorers, cards)',          [false, true,  true]],
  ['Email + SMS value-pick alerts',                     [false, true,  true]],
  ['Predictions published 24h earlier',                 [false, false, true]],
  ['Closing-line snapshot history',                     [false, false, true]],
  ['Programmatic API access',                           [false, false, true]],
  ['Custom alerts (any team, any edge)',                [false, false, true]],
  ['Weekly model-insights newsletter',                  [false, false, true]],
  ['Priority Discord access',                           [false, false, true]],
]

const FAQ = [
  {
    q: 'When are predictions published before kickoff?',
    a: "Public predictions land 12 hours before kickoff. Director’s Box subscribers see them 24 hours earlier — 36 hours total ahead of the match. The earlier the publication, the closer the model’s call sits to the opening line, before the market has fully digested team news.",
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
    a: 'A 70% pick should land 70% of the time. We track Brier score and bucketed calibration weekly on the Model page — the same numbers we use internally. Current season: 64.2% top-line accuracy at 0.018 calibration error. The page recomputes from raw call history every refresh; nothing is a marketing screenshot.',
  },
  {
    q: 'Do I have to give a card to start?',
    a: "No. Matchday is free — no card, no email gate. Season Ticket and Director’s Box require a payment method only after a 7-day free trial.",
  },
]

export default function Pricing() {
  const [theme, setTheme] = useCCTheme()
  const tick = useClock(13)
  const [billing, setBilling] = useState('mo') // 'mo' | 'yr'
  const [openFAQ, setOpenFAQ] = useState(0)
  const { isSignedIn, user } = useAuth()
  const navigate = useNavigate()
  const currentTier = isSignedIn && user ? user.tier : null

  return (
    <div
      className={`cc-root cc-${theme}`}
      style={{ position: 'relative', minHeight: '100vh', overflowX: 'hidden' }}
    >
      <Aurora />
      <div
        className="pr-page-padding"
        style={{ position: 'relative', zIndex: 2, padding: '40px 56px 80px' }}
      >
        {/* Masthead — same pattern as About.jsx */}
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
            <div className="cc-eyebrow">No. 143 · Pricing · Three Ways In</div>
          </div>
          <div style={{ display: 'flex', gap: 18, alignItems: 'center' }}>
            <CCNav active="Pricing" theme={theme} onTheme={setTheme} />
            <UpdatedBadge sec={tick} />
          </div>
        </div>

        {/* Hero */}
        <section
          className="cc-rise pr-hero"
          style={{ padding: '60px 0 40px', borderBottom: '1px solid var(--cc-line)' }}
        >
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
            <SplitWords step={50} delay={120}>
              Pricing that earns its keep.
            </SplitWords>
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
            A calibrated edge, priced for the people who actually use it. Pay monthly, pay
            yearly, or stay free — every tier ships with the same honest numbers and the
            same model.
          </p>

          {/* Monthly / Annual toggle */}
          <div className="pr-toggle" style={{ marginTop: 36 }}>
            <button
              type="button"
              className={billing === 'mo' ? 'is-on' : ''}
              onClick={() => setBilling('mo')}
            >
              Monthly
            </button>
            <button
              type="button"
              className={billing === 'yr' ? 'is-on' : ''}
              onClick={() => setBilling('yr')}
            >
              Annual{' '}
              <span style={{ marginLeft: 6, color: billing === 'yr' ? 'inherit' : 'var(--cc-gold)' }}>
                — save 25–27%
              </span>
            </button>
          </div>
        </section>

        {/* ① Plans */}
        <SectionHeader number="①" label="Plans" />
        <section
          className="pr-cards-grid"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 24,
            padding: '24px 0 50px',
          }}
        >
          {TIERS.map((t) => (
            <TierCard
              key={t.key}
              tier={t}
              billing={billing}
              currentTier={currentTier}
              onCtaClick={() => {
                // Logged-out clicks on a paid tier route through /login;
                // logged-in clicks fall through to whatever the per-tier
                // cta.to route is (Manage subscription / Upgrade / etc.).
                if (!isSignedIn && t.key !== 'matchday') {
                  navigate('/login', { state: { from: { pathname: '/pricing' } } })
                  return false
                }
                return true
              }}
            />
          ))}
        </section>

        {/* ② Compare */}
        <SectionHeader number="②" label="Compare" />
        <section
          className="pr-table-wrap"
          style={{ padding: '24px 0 50px', borderBottom: '1px solid var(--cc-line)' }}
        >
          <CompareTable rows={COMPARE_ROWS} />
        </section>

        {/* ③ FAQ */}
        <SectionHeader number="③" label="Questions, asked and answered" />
        <section style={{ padding: '24px 0 30px' }}>
          {FAQ.map((it, i) => (
            <FAQItem
              key={i}
              q={it.q}
              a={it.a}
              open={openFAQ === i}
              onToggle={() => setOpenFAQ(openFAQ === i ? -1 : i)}
            />
          ))}
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
            <span style={{ color: 'var(--cc-gold)' }}>◆ Founder pricing</span> — first 100
            Season Ticket / Director’s Box subscribers lock in $5 / $15 forever.
          </span>
          <span>
            ←{' '}
            <Link to="/" style={{ color: 'inherit' }}>
              Back to Dashboard
            </Link>
          </span>
        </div>
      </div>
    </div>
  )
}

// ── Section header ────────────────────────────────────────────────────

function SectionHeader({ number, label }) {
  return (
    <div
      className="cc-rise"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        paddingTop: 50,
        paddingBottom: 8,
        borderTop: '1px solid var(--cc-line-strong)',
      }}
    >
      <span className="cc-eyebrow" style={{ color: 'var(--cc-gold)' }}>
        {number} {label}
      </span>
    </div>
  )
}

// ── Tier card ─────────────────────────────────────────────────────────

function TierCard({ tier, billing, currentTier, onCtaClick }) {
  const price = billing === 'mo' ? tier.price.mo : tier.price.yr
  const isFree = price === 0
  const period = isFree ? null : billing === 'mo' ? '/mo' : '/yr'
  const recommended = tier.recommended

  // Tier-aware overrides — collapses the "this card vs the user's current
  // plan" relationship into one of four cases the rest of the JSX consumes.
  const isCurrent = currentTier === tier.key
  const isUpgrade =
    currentTier && TIER_ORDER[tier.key] > TIER_ORDER[currentTier]
  const isDowngrade =
    currentTier && TIER_ORDER[tier.key] < TIER_ORDER[currentTier]

  // Per-state CTA + eyebrow text. Current plan → Manage subscription;
  // higher tier → Upgrade; lower tier → Downgrade. Logged-out users keep
  // the default CTA (e.g. "Get Season Ticket"); the parent intercepts
  // those clicks via onCtaClick to route through /login first.
  let ctaLabel = tier.cta.label
  let ctaTo = tier.cta.to
  let ctaTone = recommended ? 'gold' : 'plain'
  let badge = null
  let highlightAsCurrent = false

  if (isCurrent) {
    ctaLabel = 'Manage subscription'
    ctaTo = '/billing'
    ctaTone = 'gold'
    badge = 'Your plan'
    highlightAsCurrent = true
  } else if (isUpgrade) {
    ctaLabel = `Upgrade to ${tier.name}`
    ctaTone = recommended ? 'gold' : 'plain'
  } else if (isDowngrade) {
    ctaLabel = `Switch to ${tier.name}`
    ctaTo = '/billing'
    ctaTone = 'plain'
  }

  // The "Most chosen" cut-through badge is replaced with "Your plan" when
  // the user is signed in on this tier; otherwise it shows on whichever
  // tier was originally flagged as recommended.
  const showCurrentBadge = !!badge
  const showRecommendedBadge = recommended && !badge

  // Style: a tier the user owns gets the gold border whether or not it
  // was the originally-recommended one. Without this, signing in as a
  // Director's Box user would leave Season Ticket gold-bordered while
  // the actual current plan looked secondary.
  const goldBorder = recommended || highlightAsCurrent

  function handleCtaClick(e) {
    if (onCtaClick) {
      const proceed = onCtaClick(e)
      if (proceed === false) {
        e.preventDefault()
      }
    }
  }

  return (
    <div
      className={`pr-card ${goldBorder ? 'pr-card--gold' : ''}`}
      style={{ padding: '28px 26px 24px', display: 'flex', flexDirection: 'column' }}
    >
      {showCurrentBadge && (
        <span className="pr-most-chosen">{badge}</span>
      )}
      {showRecommendedBadge && <span className="pr-most-chosen">Most chosen</span>}

      <div className="cc-eyebrow" style={{ color: 'var(--cc-muted)' }}>
        {tier.eyebrow}
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

      <p
        style={{
          fontFamily: 'var(--cc-serif)',
          fontStyle: 'italic',
          fontSize: 17,
          lineHeight: 1.45,
          color: 'var(--cc-muted)',
          margin: '12px 0 0',
          textWrap: 'pretty',
        }}
      >
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
          <span
            className="mono"
            style={{
              fontSize: 12,
              color: 'var(--cc-muted)',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
            }}
          >
            {period}
          </span>
        )}
      </div>
      {!isFree && billing === 'yr' && (
        <div
          className="mono"
          style={{
            fontSize: 10,
            color: 'var(--cc-dim)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
          }}
        >
          ≈ ${(tier.price.yr / 12).toFixed(2)}/mo, billed annually
        </div>
      )}

      <div style={{ margin: '24px 0 0', flex: 1 }}>
        {tier.bullets.map((b, i) => (
          <div key={i} className="pr-feature-row">
            <span className={`pr-glyph ${recommended ? 'pr-glyph--gold' : ''}`} aria-hidden>
              {recommended ? '◆' : '•'}
            </span>
            <span>{b}</span>
          </div>
        ))}
      </div>

      <Link
        to={ctaTo}
        onClick={handleCtaClick}
        className={`pr-cta ${ctaTone === 'gold' ? 'pr-cta--gold' : ''}`}
        style={{ marginTop: 28 }}
      >
        {ctaLabel}
      </Link>
    </div>
  )
}

// ── Compare table ─────────────────────────────────────────────────────

function CompareTable({ rows }) {
  return (
    <table className="pr-table">
      <thead>
        <tr>
          <th>Feature</th>
          <th className="col-tier">Matchday</th>
          <th className="col-tier" style={{ color: 'var(--cc-gold)' }}>
            ◆ Season Ticket
          </th>
          <th className="col-tier">Director&rsquo;s Box</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, [m, s, d]], i) => (
          <tr key={i}>
            <td>{label}</td>
            <CompareCell included={m} recommended={false} />
            <CompareCell included={s} recommended={true} />
            <CompareCell included={d} recommended={false} />
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function CompareCell({ included, recommended }) {
  if (!included) {
    return <td className="cell-mark off">—</td>
  }
  return (
    <td className={`cell-mark ${recommended ? 'gold' : 'on'}`}>
      {recommended ? '◆' : '•'}
    </td>
  )
}

// ── FAQ accordion ─────────────────────────────────────────────────────

function FAQItem({ q, a, open, onToggle }) {
  return (
    <div className={`pr-faq-item ${open ? 'open' : ''}`}>
      <button type="button" className="pr-faq-q" onClick={onToggle}>
        <span>{q}</span>
        <span className="pr-faq-mark" aria-hidden>
          +
        </span>
      </button>
      <div className="pr-faq-a">{a}</div>
    </div>
  )
}
