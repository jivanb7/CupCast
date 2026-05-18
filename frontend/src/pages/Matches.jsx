// Matches — A + B blend
// Editorial card composition with varied widths (A) + B's vertical league
// tickertape rail on the left.

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Aurora from '../components/cc/Aurora'
import Crest from '../components/cc/Crest'
import ProbBar, { ProbLegend } from '../components/cc/ProbBar'
import LiveBadge from '../components/cc/LiveBadge'
import CCNav from '../components/cc/CCNav'
import UpdatedBadge from '../components/cc/UpdatedBadge'
import CardFooter from '../components/cc/CardFooter'
import useCCTheme from '../hooks/useCCTheme'
import useClock from '../hooks/useClock'
import useUpcomingMatches from '../hooks/useUpcomingMatches'
import useRecentMatches from '../hooks/useRecentMatches'
import { LEAGUE_FLAG } from '../lib/data'
import { emptyState } from '../lib/reasons'

// Rail entries are keyed by backend league_code so the filter is stable
// across renders (display label comes from the adapter's `m.league`).
const RAIL = [
  { code: 'ALL', label: 'ALL', flag: '⚽' },
  { code: 'epl', label: 'EPL', flag: '🏴' },
  { code: 'laliga', label: 'La Liga', flag: '🇪🇸' },
  { code: 'seriea', label: 'Serie A', flag: '🇮🇹' },
  { code: 'bundesliga', label: 'Bundesliga', flag: '🇩🇪' },
  { code: 'ligue1', label: 'Ligue 1', flag: '🇫🇷' },
  { code: 'ucl', label: 'UCL', flag: '⭐' },
  { code: 'mls', label: 'MLS', flag: '🇺🇸' },
  { code: 'eredivisie', label: 'Eredivisie', flag: '🇳🇱' },
  { code: 'worldcup', label: 'WC26', flag: '🏆' },
  { code: 'championship', label: 'EFL Champ', flag: '🏴' },
]

// "Today" is computed off the kickoff timestamp converted to the viewer's
// local timezone (Pacific by default — see lib/time.js). The adapter sets
// `m.isToday` for us; pages just consume it.

export default function Matches() {
  const [theme, setTheme] = useCCTheme()
  const tick = useClock(7)
  const [tab, setTab] = useState('UPCOMING')
  const [leagueCode, setLeagueCode] = useState('ALL')

  const upcoming = useUpcomingMatches({ daysAhead: 14 })
  const recent = useRecentMatches({ daysBack: 7 })

  const isRecent = tab === 'RECENT'
  const source = isRecent ? recent : upcoming
  const { matches, loading, error } = source

  // Derive the visible slate from the active source + filters.
  const visible = useMemo(() => {
    if (!matches) return []
    return matches.filter((m) => {
      if (leagueCode !== 'ALL' && m.leagueCode !== leagueCode) return false
      if (tab === 'TODAY') {
        return m.status === 'LIVE' || m.isToday
      }
      if (tab === 'LIVE') return m.status === 'LIVE'
      if (tab === 'UPCOMING') return m.status === 'UPCOMING'
      // RECENT — already filtered server-side to completed matches
      return true
    })
  }, [matches, tab, leagueCode])

  // Rail counts always reflect the broader upcoming pool so the user can see
  // where the action is without first switching tabs.
  const railCounts = useMemo(() => {
    const counts = { ALL: upcoming.matches.length }
    for (const m of upcoming.matches) {
      if (!m.leagueCode) continue
      counts[m.leagueCode] = (counts[m.leagueCode] || 0) + 1
    }
    return counts
  }, [upcoming.matches])

  return (
    <div className={`cc-root cc-${theme}`} style={{ position: 'relative', minHeight: '100vh', overflowX: 'hidden' }}>
      <Aurora />
      <header style={{ position: 'relative', zIndex: 5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 32px', borderBottom: '1px solid var(--cc-line-strong)', background: theme === 'night' ? 'rgba(2,6,23,0.5)' : 'rgba(241,237,229,0.75)', backdropFilter: 'blur(14px)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <Link to="/" style={{ fontFamily: 'var(--cc-serif)', fontStyle: 'italic', fontWeight: 700, fontSize: 22, color: 'var(--cc-gold)', letterSpacing: '-0.02em', textDecoration: 'none' }}>CupCast</Link>
          <span style={{ color: 'var(--cc-dim)', fontFamily: 'var(--cc-mono)', fontSize: 10, letterSpacing: '0.1em' }}>{'// MATCHES'}</span>
        </div>
        <CCNav active="Matches" theme={theme} onTheme={setTheme} />
        <UpdatedBadge sec={tick} />
      </header>

      <div style={{ position: 'relative', zIndex: 2, display: 'grid', gridTemplateColumns: '240px 1fr', minHeight: 'calc(100vh - 70px)' }}>
        {/* Left rail — vertical league tickertape (B) */}
        <aside style={{ borderRight: '1px solid var(--cc-line-strong)', padding: '18px 0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 18px', color: 'var(--cc-dim)', fontFamily: 'var(--cc-mono)', fontSize: 10, letterSpacing: '0.14em', borderBottom: '1px solid var(--cc-line)' }}>
            <span>LEAGUES</span><span className="tnum">{railCounts.ALL || 0}</span>
          </div>
          <Ticker />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {RAIL.map(({ code, label, flag }) => {
              const active = leagueCode === code
              const count = railCounts[code] || 0
              return (
                <button
                  key={code}
                  onClick={() => setLeagueCode(code)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '10px 18px',
                    background: active ? 'rgba(245,158,11,0.07)' : 'transparent',
                    border: 'none',
                    borderLeft: active ? '2px solid var(--cc-gold)' : '2px solid transparent',
                    color: active ? 'var(--cc-text)' : 'var(--cc-muted)',
                    fontFamily: 'var(--cc-mono)',
                    fontSize: 12,
                    cursor: 'pointer',
                    textAlign: 'left',
                    letterSpacing: '0.04em',
                  }}
                >
                  <span style={{ width: 14 }}>{flag}</span>
                  <span style={{ flex: 1 }}>{label}</span>
                  <span className="tnum" style={{ color: active ? 'var(--cc-gold)' : 'var(--cc-dim)' }}>
                    {String(count).padStart(2, '0')}
                  </span>
                </button>
              )
            })}
          </div>
        </aside>

        {/* Right — editorial varied-width grid (A) */}
        <main style={{ padding: '24px 32px 60px' }}>
          {/* Masthead */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingBottom: 14, borderBottom: '1px solid var(--cc-line-strong)' }}>
            <h1 className="serif" style={{ margin: 0, fontSize: 56, fontStyle: 'italic', fontWeight: 600, letterSpacing: '-0.03em' }}>
              The slate.
            </h1>
            <div style={{ fontFamily: 'var(--cc-mono)', fontSize: 11, color: 'var(--cc-muted)', letterSpacing: '0.08em' }}>
              <span className="tnum" style={{ color: 'var(--cc-text)' }}>{visible.length}</span> matches
              {' · '}
              <span style={{ color: 'var(--cc-green)' }}><span className="cc-live-dot" /> {visible.filter((m) => m.status === 'LIVE').length} LIVE</span>
              {' · ◆ '}
              <span className="tnum" style={{ color: 'var(--cc-gold)' }}>{visible.filter((m) => m.valueCall).length}</span>
              {' VALUE'}
            </div>
          </div>

          {/* Tabs */}
          <div style={{ display: 'flex', gap: 0, marginTop: 14, marginBottom: 22, borderBottom: '1px solid var(--cc-line)' }}>
            {['TODAY', 'LIVE', 'UPCOMING', 'RECENT'].map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: '10px 18px',
                  color: t === tab ? 'var(--cc-gold)' : 'var(--cc-muted)',
                  borderBottom: t === tab ? '2px solid var(--cc-gold)' : '2px solid transparent',
                  fontFamily: 'var(--cc-mono)',
                  fontSize: 11,
                  letterSpacing: '0.12em',
                  cursor: 'pointer',
                  marginBottom: -1,
                  transition: 'color 200ms',
                }}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Content area: loading / error / empty / grid */}
          {loading ? (
            <SlateSkeleton />
          ) : error ? (
            <SlateMessage copy={emptyState('error')} />
          ) : visible.length === 0 ? (
            <SlateMessage copy={emptyState('noMatches')} />
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(6, 1fr)',
                gap: 18,
                transition: 'opacity 200ms',
              }}
            >
              {visible.map((m, i) => {
                const featured = m.valueCall || m.status === 'LIVE'
                const span = featured ? 3 : 2
                return (
                  <div key={m.id} style={{ gridColumn: `span ${span}` }}>
                    <MatchCardEd m={m} idx={i} feature={featured} />
                  </div>
                )
              })}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

function SlateMessage({ copy }) {
  return (
    <div
      style={{
        padding: '60px 0',
        textAlign: 'center',
        fontFamily: 'var(--cc-serif)',
        fontStyle: 'italic',
        fontSize: 22,
        lineHeight: 1.4,
        color: 'var(--cc-muted)',
        maxWidth: 640,
        margin: '0 auto',
      }}
    >
      {copy}
    </div>
  )
}

function SlateSkeleton() {
  // Block silhouettes mirroring the final card layout — no spinners.
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 18 }}>
      {[3, 2, 2, 3, 2, 3, 2, 2].map((span, i) => (
        <div
          key={i}
          style={{
            gridColumn: `span ${span}`,
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            borderRadius: 6,
            height: 168,
            opacity: 0.55,
            animation: `cc-rise 600ms ${i * 80}ms cubic-bezier(.2,.7,.2,1) both`,
          }}
        />
      ))}
    </div>
  )
}

function Ticker() {
  const items = [
    ['EPL', '+1.4%', 'g'], ['UCL', '+4.2%', 'g'], ['LIGA', '+0.8%', 'g'],
    ['SERIE', '-0.2%', 'r'], ['BUND', '+5.8%', 'g'], ['LIG1', '+0.5%', 'g'],
    ['ERED', '-0.4%', 'r'], ['MLS', '+1.1%', 'g'],
  ]
  return (
    <div style={{ borderTop: '1px solid var(--cc-line)', borderBottom: '1px solid var(--cc-line)', overflow: 'hidden', height: 70, position: 'relative', background: 'rgba(245,158,11,0.02)' }}>
      <div style={{ animation: 'cc-vert 60s linear infinite', display: 'flex', flexDirection: 'column' }}>
        {[...items, ...items].map(([l, v, c], i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 18px', fontFamily: 'var(--cc-mono)', fontSize: 11, letterSpacing: '0.08em', color: 'var(--cc-muted)', borderBottom: '1px dashed var(--cc-line)' }}>
            <span>{l}</span>
            <span className="tnum" style={{ color: c === 'g' ? 'var(--cc-green)' : 'var(--cc-red)' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function MatchCardEd({ m, idx, feature }) {
  const isLive = m.status === 'LIVE'
  const homeScore = isLive || m.status === 'FT' ? m.score?.split('-')[0] : null
  const awayScore = isLive || m.status === 'FT' ? m.score?.split('-')[1] : null
  return (
    <Link to={`/match/${m.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
      <div
        className="cc-rise cc-hover"
        style={{
          background: feature ? 'var(--cc-surface)' : 'transparent',
          border: feature ? '1px solid var(--cc-line)' : 'none',
          borderTop: feature ? '1px solid var(--cc-line)' : '1px solid var(--cc-line-strong)',
          borderBottom: feature ? '1px solid var(--cc-line)' : '1px solid var(--cc-line)',
          borderRadius: feature ? 6 : 0,
          padding: feature ? 22 : '18px 0',
          animationDelay: `${idx * 60}ms`,
          cursor: 'pointer',
          display: 'block',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <span style={{ fontFamily: 'var(--cc-mono)', fontSize: 10, color: 'var(--cc-muted)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            {LEAGUE_FLAG[m.league] || '⚽'} {m.league}{m.stage ? ` · ${m.stage}` : ''}
          </span>
          {isLive ? (
            <LiveBadge minute={m.minute || 0} />
          ) : (
            <span className="mono tnum" style={{ fontSize: 11, color: 'var(--cc-muted)' }}>
              {m.isToday ? m.kickoff : `${m.kickoffDateLabel} · ${m.kickoff}`}
            </span>
          )}
        </div>

        {feature ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 14, alignItems: 'center', padding: '8px 0' }}>
            <TeamBlock short={m.homeShort} crest={m.homeCrest} name={m.home} score={homeScore} winning={isLive && +homeScore > +awayScore} />
            <span className="serif tnum" style={{ fontSize: 28, fontStyle: 'italic', color: 'var(--cc-muted)', fontWeight: 600, letterSpacing: '-0.03em' }}>
              {homeScore != null ? '·' : 'vs'}
            </span>
            <TeamBlock short={m.awayShort} crest={m.awayCrest} name={m.away} score={awayScore} winning={isLive && +homeScore < +awayScore} alignRight />
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <CompactRow short={m.homeShort} crest={m.homeCrest} name={m.home} prob={m.probH} />
            <CompactRow short={m.awayShort} crest={m.awayCrest} name={m.away} prob={m.probA} />
          </div>
        )}

        <div style={{ marginTop: 14 }}>
          <ProbBar h={m.probH} d={m.probD} a={m.probA} />
          <ProbLegend h={m.probH} d={m.probD} a={m.probA} />
        </div>
        <CardFooter pick={m.callShort} conf={m.callConf} value={m.valueCall} edge={m.edge} />
      </div>
    </Link>
  )
}

function TeamBlock({ short, crest, name, score, winning, alignRight }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexDirection: alignRight ? 'row-reverse' : 'row', justifyContent: alignRight ? 'flex-end' : 'flex-start' }}>
      <Crest short={short} crestUrl={crest} size={36} />
      <div style={{ textAlign: alignRight ? 'right' : 'left' }}>
        <div style={{ fontFamily: 'var(--cc-display)', fontSize: 17, fontWeight: winning ? 700 : 500, letterSpacing: '-0.01em' }}>{name}</div>
        {score != null ? (
          <div className="serif tnum" style={{ fontSize: 28, fontStyle: 'italic', fontWeight: 600, color: 'var(--cc-text)', letterSpacing: '-0.02em', lineHeight: 1, marginTop: 2 }}>{score}</div>
        ) : null}
      </div>
    </div>
  )
}

function CompactRow({ short, crest, name, prob }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <Crest short={short} crestUrl={crest} size={22} />
      <div style={{ flex: 1, fontFamily: 'var(--cc-display)', fontSize: 14, fontWeight: 500 }}>{name}</div>
      <div className="mono tnum" style={{ fontSize: 11, color: 'var(--cc-muted)' }}>{prob}%</div>
    </div>
  )
}
