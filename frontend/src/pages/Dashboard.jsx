// Dashboard — Direction C (vertical scroll narrative)
// Marquee → slate (h-scroll snap) → form chart → value accordion.

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Aurora from '../components/cc/Aurora'
import Crest from '../components/cc/Crest'
import Eyebrow from '../components/cc/Eyebrow'
import ProbBar, { ProbLegend } from '../components/cc/ProbBar'
import LiveBadge from '../components/cc/LiveBadge'
import CCNav from '../components/cc/CCNav'
import UpdatedBadge from '../components/cc/UpdatedBadge'
import SplitWords from '../components/cc/SplitWords'
import CardFooter from '../components/cc/CardFooter'
import useCountUp from '../hooks/useCountUp'
import useCCTheme from '../hooks/useCCTheme'
import useClock from '../hooks/useClock'
import useInView from '../hooks/useInView'
import useUpcomingMatches from '../hooks/useUpcomingMatches'
import useModelPerformance from '../hooks/useModelPerformance'
import { LEAGUE_FLAG } from '../lib/data'
import { pickFor, emptyState } from '../lib/reasons'
import { tzAbbreviation } from '../lib/time'


function pickMarquee(matches) {
  if (!matches || matches.length === 0) return null
  const ranked = [...matches].sort((a, b) => {
    if (b.valueCall !== a.valueCall) return b.valueCall ? 1 : -1
    if (b.edge !== a.edge) return b.edge - a.edge
    return b.callConf - a.callConf
  })
  return ranked[0]
}

export default function Dashboard() {
  const [theme, setTheme] = useCCTheme()
  const tick = useClock(12)
  const upcoming = useUpcomingMatches({ daysAhead: 14 })
  const perf = useModelPerformance()

  const marquee = useMemo(() => pickMarquee(upcoming.matches), [upcoming.matches])

  const slate = useMemo(() => {
    if (!upcoming.matches?.length) return []
    // Prefer matches today, then nearest upcoming. Skip the marquee match
    // itself so the slate doesn't repeat the front-door card.
    const sorted = [...upcoming.matches].sort((a, b) => {
      const ad = a.matchDate || ''
      const bd = b.matchDate || ''
      return ad.localeCompare(bd)
    })
    return sorted.filter((m) => !marquee || m.id !== marquee.id).slice(0, 7)
  }, [upcoming.matches, marquee])

  const valuePicks = useMemo(() => {
    if (!upcoming.matches?.length) return []
    return upcoming.matches
      .filter((m) => m.valueCall)
      .sort((a, b) => b.edge - a.edge)
      .slice(0, 6)
      .map((m) => ({
        id: m.id,
        match: `${m.home} v ${m.away}`,
        league: m.league,
        pick: m.callTeam,
        edge: m.edge,
        conf: m.callConf,
        fairOdds: m.fairOdds,
        marketOdds: m.marketOdds,
        kickoff: m.kickoff,
      }))
  }, [upcoming.matches])

  const liveCount = useMemo(
    () => upcoming.matches.filter((m) => m.status === 'LIVE').length,
    [upcoming.matches]
  )

  const todayCount = useMemo(
    () => upcoming.matches.filter((m) => m.isToday).length,
    [upcoming.matches]
  )

  return (
    <div className={`cc-root cc-${theme}`} style={{ position: 'relative', minHeight: '100vh', overflowX: 'hidden' }}>
      <Aurora />

      <header
        style={{
          position: 'fixed',
          top: 18,
          left: 0,
          right: 0,
          zIndex: 50,
          display: 'flex',
          justifyContent: 'center',
          pointerEvents: 'none',
        }}
      >
        <div
          style={{
            pointerEvents: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: 18,
            padding: '10px 18px',
            background: theme === 'night' ? 'rgba(2,6,23,0.6)' : 'rgba(241,237,229,0.75)',
            backdropFilter: 'blur(14px)',
            border: '1px solid var(--cc-line-strong)',
            borderRadius: 999,
          }}
        >
          <Link
            to="/"
            style={{
              fontFamily: 'var(--cc-serif)',
              fontStyle: 'italic',
              fontWeight: 700,
              fontSize: 16,
              color: 'var(--cc-gold)',
              letterSpacing: '-0.02em',
              textDecoration: 'none',
            }}
          >
            CupCast
          </Link>
          <span style={{ color: 'var(--cc-dim)' }}>·</span>
          <CCNav active="Dashboard" theme={theme} onTheme={setTheme} compact />
          <span style={{ color: 'var(--cc-dim)' }}>·</span>
          <UpdatedBadge sec={tick} />
        </div>
      </header>

      <div
        style={{
          position: 'fixed',
          right: 32,
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: 40,
          display: 'grid',
          gap: 22,
          pointerEvents: 'none',
        }}
      >
        {['Marquee', 'Slate', 'Form', 'Value'].map((l, i) => (
          <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              style={{
                fontFamily: 'var(--cc-mono)',
                fontSize: 9,
                letterSpacing: '0.16em',
                color: 'var(--cc-dim)',
                textTransform: 'uppercase',
                writingMode: 'vertical-rl',
                transform: 'rotate(180deg)',
              }}
            >
              0{i + 1} · {l}
            </span>
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: 3,
                background: i === 0 ? 'var(--cc-gold)' : 'var(--cc-dim)',
              }}
            />
          </div>
        ))}
      </div>

      <div style={{ position: 'relative', zIndex: 2, paddingTop: 100, paddingBottom: 80 }}>
        <Section1Marquee m={marquee} loading={upcoming.loading} error={upcoming.error} />

        <Divider
          label="② Today's slate"
          right={`${String(todayCount).padStart(2, '0')} matches · ${liveCount} live`}
        />
        <Section2Slate slate={slate} loading={upcoming.loading} error={upcoming.error} />

        <Divider
          label="③ Form, this week"
          right={
            perf.data
              ? `Season acc · ${perf.data.accuracy}%`
              : '—'
          }
        />
        <Section3Form perf={perf.data} loading={perf.loading} error={perf.error} />

        <Divider
          label="④ Value desk"
          right="Where the model disagrees with the market"
          gold
        />
        <Section4Value picks={valuePicks} loading={upcoming.loading} />

        <PageFooter />
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// Section 1 — Marquee
// ──────────────────────────────────────────────────────────────────────

function Section1Marquee({ m, loading, error }) {
  if (loading) return <MarqueeSkeleton />
  if (error) return <MarqueeMessage copy={emptyState('error')} />
  if (!m) return <MarqueeMessage copy={emptyState('noMatches')} />
  return <MarqueeContent m={m} />
}

function MarqueeContent({ m }) {
  const valH = useCountUp(m.probH, { duration: 700, delay: 400 })
  const valD = useCountUp(m.probD, { duration: 700, delay: 500 })
  const valA = useCountUp(m.probA, { duration: 700, delay: 600 })
  const [whyRef, whyVis] = useInView()

  const subtitle = m.valueCall
    ? `The model and the book disagree. ${m.callTeam} is the call — by +${m.edge.toFixed(1)} points over the book.`
    : `The numbers tilt to ${m.callTeam} at ${m.callConf}%. Fair price ${m.fairOdds.toFixed(2)} against a book of ${m.marketOdds.toFixed(2)}.`

  return (
    <section style={{ maxWidth: 980, margin: '0 auto', padding: '0 40px 100px' }}>
      <div
        className="cc-rise"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          marginBottom: 28,
          fontFamily: 'var(--cc-mono)',
          fontSize: 11,
          letterSpacing: '0.16em',
          color: 'var(--cc-muted)',
          textTransform: 'uppercase',
        }}
      >
        <span style={{ color: 'var(--cc-gold)' }}>① {m.isToday ? 'Tonight' : (m.kickoffDateLabel || 'Up next')}</span>
        <span style={{ flex: 1, height: 1, background: 'var(--cc-line)' }} />
        <span>{m.league}{m.stage ? ` · ${m.stage}` : ''}</span>
        {m.kickoff && <span>{m.kickoff} {tzAbbreviation()}</span>}
        {m.venue && <span style={{ color: 'var(--cc-text)' }}>{m.venue}</span>}
      </div>

      <h1
        className="cc-rise"
        style={{
          fontFamily: 'var(--cc-serif)',
          fontStyle: 'italic',
          fontWeight: 600,
          fontSize: 96,
          letterSpacing: '-0.04em',
          lineHeight: 0.95,
          margin: '0 0 22px',
          animationDelay: '80ms',
        }}
      >
        {m.home}
        <br />
        <span
          style={{
            fontStyle: 'normal',
            color: 'var(--cc-muted)',
            fontWeight: 400,
            letterSpacing: '-0.03em',
          }}
        >
          versus
        </span>
        <br />
        {m.away}.
      </h1>

      <p
        style={{
          fontSize: 19,
          lineHeight: 1.5,
          color: 'var(--cc-muted)',
          maxWidth: 640,
          margin: '0 0 42px',
        }}
      >
        <SplitWords delay={200} step={40}>
          {subtitle}
        </SplitWords>
      </p>

      <div
        className="cc-rise"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 0,
          animationDelay: '240ms',
          border: '1px solid var(--cc-line-strong)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <ProbCellAnim
          label={`${m.home} wins`}
          sub={m.callKey === 'H' ? '◆ The Call' : null}
          team={m.homeShort}
          val={valH}
          c="var(--cc-green)"
          highlight={m.callKey === 'H'}
        />
        <ProbCellAnim
          label="Draw"
          sub={m.callKey === 'D' ? '◆ The Call' : null}
          team="X"
          val={valD}
          c="var(--cc-amber)"
          highlight={m.callKey === 'D'}
        />
        <ProbCellAnim
          label={`${m.away} wins`}
          sub={m.callKey === 'A' ? '◆ The Call' : null}
          team={m.awayShort}
          val={valA}
          c="var(--cc-red)"
          highlight={m.callKey === 'A'}
        />
      </div>

      <div
        ref={whyRef}
        className="cc-rise"
        style={{
          marginTop: 56,
          animationDelay: '320ms',
          display: 'grid',
          gridTemplateColumns: '200px 1fr',
          gap: 32,
          paddingTop: 32,
          borderTop: '1px solid var(--cc-line)',
        }}
      >
        <div>
          <Eyebrow gold>◆ The Call</Eyebrow>
          <div
            className="serif"
            style={{
              fontSize: 38,
              fontStyle: 'italic',
              fontWeight: 600,
              marginTop: 8,
              letterSpacing: '-0.02em',
              lineHeight: 1,
              color: 'var(--cc-gold)',
            }}
          >
            {m.callTeam}
          </div>
          <div
            style={{
              marginTop: 12,
              fontFamily: 'var(--cc-mono)',
              fontSize: 11,
              color: 'var(--cc-muted)',
              letterSpacing: '0.06em',
              lineHeight: 1.7,
            }}
          >
            CONFIDENCE&nbsp;<span className="tnum" style={{ color: 'var(--cc-text)' }}>{m.callConf}%</span>
            <br />
            FAIR&nbsp;<span className="tnum" style={{ color: 'var(--cc-text)' }}>{m.fairOdds.toFixed(2)}</span>
            <br />
            BOOK&nbsp;<span className="tnum" style={{ color: 'var(--cc-text)' }}>{m.marketOdds.toFixed(2)}</span>
            <br />
            {m.valueCall && (
              <span style={{ color: 'var(--cc-gold)' }}>
                ◆ VALUE&nbsp;<span className="tnum">+{m.edge.toFixed(1)}%</span>
              </span>
            )}
          </div>
        </div>

        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 18 }}>
          {pickFor(m, 5).map((w, i, arr) => (
            <li
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '40px 1fr',
                gap: 16,
                paddingBottom: 18,
                borderBottom: i === arr.length - 1 ? 'none' : '1px solid var(--cc-line)',
                opacity: whyVis ? 1 : 0,
                transform: whyVis ? 'none' : 'translateY(12px)',
                transition: `opacity 420ms ease ${i * 100}ms, transform 420ms ease ${i * 100}ms`,
              }}
            >
              <span
                className="serif tnum"
                style={{
                  fontSize: 32,
                  fontStyle: 'italic',
                  fontWeight: 600,
                  color: 'var(--cc-gold)',
                  letterSpacing: '-0.04em',
                  lineHeight: 1,
                }}
              >
                0{i + 1}
              </span>
              <span style={{ fontFamily: 'var(--cc-serif)', fontSize: 19, lineHeight: 1.4, color: 'var(--cc-text)' }}>
                {w}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div style={{ marginTop: 28 }}>
        <Link
          to={`/match/${m.id}`}
          style={{
            fontFamily: 'var(--cc-mono)',
            fontSize: 11,
            letterSpacing: '0.12em',
            color: 'var(--cc-gold)',
            textDecoration: 'none',
            textTransform: 'uppercase',
          }}
        >
          → Open match brief
        </Link>
      </div>
    </section>
  )
}

function MarqueeSkeleton() {
  return (
    <section style={{ maxWidth: 980, margin: '0 auto', padding: '0 40px 100px' }}>
      <div
        style={{
          height: 360,
          background: 'var(--cc-surface)',
          border: '1px solid var(--cc-line)',
          borderRadius: 8,
          opacity: 0.5,
          animation: 'cc-rise 600ms cubic-bezier(.2,.7,.2,1) both',
        }}
      />
    </section>
  )
}

function MarqueeMessage({ copy }) {
  return (
    <section style={{ maxWidth: 980, margin: '0 auto', padding: '40px 40px 100px', textAlign: 'center' }}>
      <div
        style={{
          fontFamily: 'var(--cc-serif)',
          fontStyle: 'italic',
          fontSize: 28,
          color: 'var(--cc-muted)',
          lineHeight: 1.4,
          maxWidth: 640,
          margin: '0 auto',
        }}
      >
        {copy}
      </div>
    </section>
  )
}

function ProbCellAnim({ label, sub, team, val, c, highlight }) {
  const intV = Math.round(val)
  return (
    <div
      style={{
        padding: '28px 24px',
        position: 'relative',
        borderRight: '1px solid var(--cc-line)',
        background: highlight ? 'rgba(245,158,11,0.04)' : 'transparent',
      }}
    >
      <Eyebrow>{label}</Eyebrow>
      {sub && <div className="cc-eyebrow" style={{ color: 'var(--cc-gold)', marginTop: 4 }}>{sub}</div>}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 10 }}>
        <span
          className="serif tnum"
          style={{
            fontSize: 76,
            fontStyle: 'italic',
            fontWeight: 600,
            color: highlight ? 'var(--cc-gold)' : 'var(--cc-text)',
            letterSpacing: '-0.04em',
            lineHeight: 0.9,
          }}
        >
          {intV}
        </span>
        <span className="serif" style={{ fontSize: 32, color: 'var(--cc-muted)', fontStyle: 'italic' }}>
          %
        </span>
      </div>
      <div
        style={{
          marginTop: 12,
          height: 3,
          background: c,
          width: `${intV}%`,
          transition: 'width 700ms cubic-bezier(.2,.7,.2,1)',
        }}
      />
      <div
        style={{
          marginTop: 8,
          fontFamily: 'var(--cc-mono)',
          fontSize: 10,
          color: 'var(--cc-muted)',
          letterSpacing: '0.1em',
        }}
      >
        {team}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// Layout helpers
// ──────────────────────────────────────────────────────────────────────

function Divider({ label, right, gold }) {
  return (
    <div
      style={{
        maxWidth: 980,
        margin: '0 auto',
        padding: '0 40px',
        display: 'flex',
        alignItems: 'center',
        gap: 22,
        fontFamily: 'var(--cc-mono)',
        fontSize: 11,
        letterSpacing: '0.16em',
        textTransform: 'uppercase',
        color: 'var(--cc-muted)',
      }}
    >
      <span style={{ color: gold ? 'var(--cc-gold)' : 'var(--cc-text)' }}>{label}</span>
      <span style={{ flex: 1, height: 1, background: 'var(--cc-line)' }} />
      <span>{right}</span>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// Section 2 — Slate
// ──────────────────────────────────────────────────────────────────────

function Section2Slate({ slate, loading, error }) {
  if (loading) return <SlateSkeleton />
  if (error) return <SlateMessage copy={emptyState('error')} />
  if (slate.length === 0) return <SlateMessage copy={emptyState('noMatches')} />
  return (
    <section style={{ padding: '48px 0 80px' }}>
      <div
        style={{
          display: 'flex',
          gap: 18,
          padding: '0 max(40px, calc((100vw - 1100px) / 2))',
          overflowX: 'auto',
          scrollSnapType: 'x mandatory',
          scrollPadding: 40,
        }}
      >
        {slate.map((m, i) => (
          <SnapCard m={m} key={m.id} idx={i} />
        ))}
      </div>
    </section>
  )
}

function SlateSkeleton() {
  return (
    <section style={{ padding: '48px 0 80px' }}>
      <div
        style={{
          display: 'flex',
          gap: 18,
          padding: '0 max(40px, calc((100vw - 1100px) / 2))',
        }}
      >
        {[0, 1, 2, 3, 4].map((i) => (
          <div
            key={i}
            style={{
              flex: '0 0 280px',
              height: 220,
              background: 'var(--cc-surface)',
              border: '1px solid var(--cc-line)',
              borderRadius: 8,
              opacity: 0.5,
              animation: `cc-rise 600ms ${i * 80}ms cubic-bezier(.2,.7,.2,1) both`,
            }}
          />
        ))}
      </div>
    </section>
  )
}

function SlateMessage({ copy }) {
  return (
    <section style={{ padding: '48px 0 80px', textAlign: 'center' }}>
      <div
        style={{
          fontFamily: 'var(--cc-serif)',
          fontStyle: 'italic',
          fontSize: 22,
          color: 'var(--cc-muted)',
          maxWidth: 640,
          margin: '0 auto',
        }}
      >
        {copy}
      </div>
    </section>
  )
}

function SnapCard({ m, idx }) {
  const isLive = m.status === 'LIVE'
  const homeScore = isLive || m.status === 'FT' ? m.score?.split('-')[0] : null
  const awayScore = isLive || m.status === 'FT' ? m.score?.split('-')[1] : null
  return (
    <Link to={`/match/${m.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
      <div
        className="cc-rise cc-hover"
        style={{
          flex: '0 0 280px',
          scrollSnapAlign: 'start',
          background: 'var(--cc-surface)',
          border: '1px solid var(--cc-line)',
          borderRadius: 8,
          padding: 22,
          animationDelay: `${idx * 80}ms`,
          cursor: 'pointer',
          display: 'block',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
          <span
            style={{
              fontFamily: 'var(--cc-mono)',
              fontSize: 10,
              color: 'var(--cc-muted)',
              letterSpacing: '0.1em',
            }}
          >
            {LEAGUE_FLAG[m.league] || '⚽'} {String(m.league).toUpperCase()}
          </span>
          {isLive ? (
            <LiveBadge minute={m.minute || 0} />
          ) : (
            <span className="mono tnum" style={{ fontSize: 10, color: 'var(--cc-muted)' }}>
              {m.isToday ? m.kickoff : `${m.kickoffDateLabel} · ${m.kickoff}`}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 18 }}>
          <SnapTeamRow short={m.homeShort} crest={m.homeCrest} name={m.home} score={homeScore} />
          <SnapTeamRow short={m.awayShort} crest={m.awayCrest} name={m.away} score={awayScore} />
        </div>
        <ProbBar h={m.probH} d={m.probD} a={m.probA} />
        <ProbLegend h={m.probH} d={m.probD} a={m.probA} />
        <CardFooter pick={m.callShort} conf={m.callConf} value={m.valueCall} edge={m.edge} />
      </div>
    </Link>
  )
}

function SnapTeamRow({ short, crest, name, score }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <Crest short={short} crestUrl={crest} size={26} />
      <div style={{ flex: 1, fontFamily: 'var(--cc-display)', fontSize: 14, fontWeight: 500 }}>
        {name}
      </div>
      {score != null && (
        <div
          className="serif tnum"
          style={{
            fontSize: 22,
            fontStyle: 'italic',
            fontWeight: 600,
            color: 'var(--cc-text)',
            letterSpacing: '-0.02em',
          }}
        >
          {score}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// Section 3 — Form, this week
// ──────────────────────────────────────────────────────────────────────

function Section3Form({ perf, loading, error }) {
  if (loading) {
    return (
      <section style={{ maxWidth: 980, margin: '0 auto', padding: '48px 40px 80px' }}>
        <div
          style={{
            height: 280,
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            borderRadius: 8,
            opacity: 0.5,
            animation: 'cc-rise 600ms cubic-bezier(.2,.7,.2,1) both',
          }}
        />
      </section>
    )
  }
  if (error || !perf) {
    return (
      <section style={{ maxWidth: 980, margin: '0 auto', padding: '48px 40px 80px', textAlign: 'center' }}>
        <div style={{ fontFamily: 'var(--cc-serif)', fontStyle: 'italic', fontSize: 22, color: 'var(--cc-muted)' }}>
          {emptyState('calibrating')}
        </div>
      </section>
    )
  }

  const deltaPositive = perf.accuracyDelta >= 0

  return (
    <section style={{ maxWidth: 980, margin: '0 auto', padding: '48px 40px 80px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, alignItems: 'end', marginBottom: 30 }}>
        <div>
          <Eyebrow>This week</Eyebrow>
          <div
            className="serif tnum"
            style={{
              fontSize: 132,
              fontStyle: 'italic',
              fontWeight: 600,
              letterSpacing: '-0.04em',
              lineHeight: 0.9,
              marginTop: 8,
            }}
          >
            {perf.accuracy}
            <span style={{ fontSize: 56, color: 'var(--cc-muted)' }}>%</span>
          </div>
          <div
            style={{
              marginTop: 6,
              fontFamily: 'var(--cc-mono)',
              fontSize: 11,
              color: deltaPositive ? 'var(--cc-green)' : 'var(--cc-red)',
              letterSpacing: '0.08em',
            }}
          >
            {deltaPositive ? '▲' : '▼'} {deltaPositive ? '+' : ''}{perf.accuracyDelta} vs season avg
          </div>
        </div>
        <p
          style={{
            fontFamily: 'var(--cc-serif)',
            fontStyle: 'italic',
            fontSize: 22,
            lineHeight: 1.4,
            margin: 0,
            color: 'var(--cc-muted)',
            paddingBottom: 14,
          }}
        >
          F1 macro <span style={{ color: 'var(--cc-text)' }} className="tnum">{perf.f1Macro}</span> · log loss <span style={{ color: 'var(--cc-text)' }} className="tnum">{perf.logLoss}</span>
        </p>
      </div>

      {perf.lastWeek.length >= 2 ? (
        <RollingChart data={perf.lastWeek} />
      ) : (
        <div
          style={{
            padding: '40px 0',
            fontFamily: 'var(--cc-serif)',
            fontStyle: 'italic',
            fontSize: 18,
            color: 'var(--cc-muted)',
            textAlign: 'center',
          }}
        >
          {emptyState('calibrating')}
        </div>
      )}

      {perf.perLeague.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${Math.min(5, perf.perLeague.length)}, 1fr)`,
            gap: 0,
            marginTop: 36,
            borderTop: '1px solid var(--cc-line)',
          }}
        >
          {perf.perLeague.slice(0, 5).map((l, i, arr) => (
            <div
              key={l.code || i}
              style={{
                padding: '18px 16px',
                borderRight: i < arr.length - 1 ? '1px solid var(--cc-line)' : 'none',
              }}
            >
              <div className="cc-eyebrow" style={{ fontSize: 9 }}>
                {l.flag} {l.name}
              </div>
              <div
                className="serif tnum"
                style={{
                  fontSize: 28,
                  fontStyle: 'italic',
                  fontWeight: 600,
                  marginTop: 4,
                  letterSpacing: '-0.02em',
                }}
              >
                {l.acc}
                <span style={{ fontSize: 12, color: 'var(--cc-muted)' }}>%</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function RollingChart({ data }) {
  const w = 880
  const h = 220
  // Dynamic y-range: pad ±10pp around the actual data so real numbers in
  // the 30–50 band don't get clipped or look flat against a 40–90 axis.
  const accs = data.map((d) => d.acc)
  const dataMin = Math.min(...accs)
  const dataMax = Math.max(...accs)
  const min = Math.max(0, Math.floor((dataMin - 10) / 10) * 10)
  const max = Math.min(100, Math.ceil((dataMax + 10) / 10) * 10)
  const span = Math.max(1, max - min)
  const pts = data.map((d, i) => ({
    x: (i / Math.max(1, data.length - 1)) * w,
    y: h - ((d.acc - min) / span) * h,
    ...d,
  }))
  const path = pts.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ')
  const area = `${path} L${w},${h} L0,${h} Z`
  const ticks = []
  for (let v = Math.ceil(min / 10) * 10; v <= max; v += 10) ticks.push(v)
  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${w} ${h + 30}`} style={{ width: '100%', height: h + 30, display: 'block' }}>
        <defs>
          <linearGradient id="cFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--cc-gold)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--cc-gold)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((v) => {
          const y = h - ((v - min) / span) * h
          return (
            <g key={v}>
              <line x1="0" x2={w} y1={y} y2={y} stroke="var(--cc-line)" strokeDasharray="2 4" />
              <text
                x={w - 4}
                y={y - 4}
                textAnchor="end"
                fontSize="9"
                fill="var(--cc-dim)"
                fontFamily="var(--cc-mono)"
                letterSpacing="0.1em"
              >
                {v}%
              </text>
            </g>
          )
        })}
        <path d={area} fill="url(#cFill)" />
        <path
          d={path}
          fill="none"
          stroke="var(--cc-gold)"
          strokeWidth="2"
          strokeDasharray="2000"
          strokeDashoffset="2000"
          style={{ animation: 'cc-line-in 1200ms ease-out forwards' }}
        />
        {pts.map((p, i) => (
          <g key={i} style={{ opacity: 0, animation: `cc-fade-in 400ms ease-out ${800 + i * 80}ms forwards` }}>
            <circle
              cx={p.x}
              cy={p.y}
              r={i === pts.length - 1 ? 6 : 3.5}
              fill={i === pts.length - 1 ? 'var(--cc-gold)' : 'var(--cc-bg)'}
              stroke="var(--cc-gold)"
              strokeWidth="2"
            />
            <text
              x={p.x}
              y={h + 18}
              textAnchor="middle"
              fontSize="9"
              fill="var(--cc-dim)"
              fontFamily="var(--cc-mono)"
              letterSpacing="0.1em"
            >
              {(p.d || '').split(' ')[1] || p.d}
            </text>
            <text
              x={p.x}
              y={p.y - 12}
              textAnchor="middle"
              fontSize="11"
              fill={i === pts.length - 1 ? 'var(--cc-gold)' : 'var(--cc-text)'}
              fontFamily="var(--cc-mono)"
              fontWeight="600"
            >
              {p.acc}
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// Section 4 — Value desk
// ──────────────────────────────────────────────────────────────────────

function Section4Value({ picks, loading }) {
  if (loading) {
    return (
      <section style={{ maxWidth: 980, margin: '0 auto', padding: '48px 40px 60px' }}>
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            style={{
              height: 84,
              borderTop: i === 0 ? '1px solid var(--cc-line-strong)' : 'none',
              borderBottom: '1px solid var(--cc-line-strong)',
              background: 'var(--cc-surface)',
              opacity: 0.5,
              animation: `cc-rise 600ms ${i * 80}ms cubic-bezier(.2,.7,.2,1) both`,
            }}
          />
        ))}
      </section>
    )
  }
  if (picks.length === 0) {
    return (
      <section style={{ maxWidth: 980, margin: '0 auto', padding: '48px 40px 60px', textAlign: 'center' }}>
        <div
          style={{
            fontFamily: 'var(--cc-serif)',
            fontStyle: 'italic',
            fontSize: 22,
            color: 'var(--cc-muted)',
            maxWidth: 640,
            margin: '0 auto',
          }}
        >
          {emptyState('noValue')}
        </div>
      </section>
    )
  }
  return (
    <section style={{ maxWidth: 980, margin: '0 auto', padding: '48px 40px 60px' }}>
      {picks.map((v, i) => (
        <ValueAccord key={v.id} v={v} idx={i} expanded={i === 0} />
      ))}
    </section>
  )
}

function ValueAccord({ v, idx, expanded }) {
  const [open, setOpen] = useState(expanded)
  const reasonText = useMemo(() => {
    // Use the reasoning library to fill the accordion's "why" line.
    const bullets = pickFor(
      {
        id: v.id,
        home: v.match.split(' v ')[0],
        away: v.match.split(' v ')[1],
        callTeam: v.pick,
        fairOdds: v.fairOdds,
        marketOdds: v.marketOdds,
      },
      1
    )
    return bullets[0] || `The model has ${v.pick} at ${v.conf}% — the book is mispriced.`
  }, [v])

  return (
    <div
      style={{
        borderTop: idx === 0 ? '1px solid var(--cc-line-strong)' : 'none',
        borderBottom: '1px solid var(--cc-line-strong)',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          width: '100%',
          textAlign: 'left',
          background: 'none',
          border: 'none',
          padding: '24px 0',
          cursor: 'pointer',
          color: 'inherit',
          display: 'grid',
          gridTemplateColumns: 'auto 1fr auto auto',
          gap: 24,
          alignItems: 'center',
        }}
      >
        <span
          className="serif tnum"
          style={{
            fontSize: 56,
            fontStyle: 'italic',
            fontWeight: 600,
            color: 'var(--cc-gold)',
            letterSpacing: '-0.04em',
            lineHeight: 0.9,
            minWidth: 110,
          }}
        >
          +{v.edge.toFixed(1)}
          <span style={{ fontSize: 24, color: 'var(--cc-muted)' }}>%</span>
        </span>
        <span>
          <Eyebrow>{v.league}</Eyebrow>
          <div
            className="serif"
            style={{
              fontSize: 26,
              fontWeight: 600,
              lineHeight: 1.1,
              letterSpacing: '-0.01em',
              marginTop: 4,
            }}
          >
            {v.match}
          </div>
        </span>
        <span
          style={{
            fontFamily: 'var(--cc-mono)',
            fontSize: 11,
            color: 'var(--cc-muted)',
            letterSpacing: '0.08em',
          }}
        >
          ◆ {String(v.pick).toUpperCase()} · <span className="tnum">{v.conf}%</span>
        </span>
        <span
          style={{
            width: 32,
            height: 32,
            borderRadius: '50%',
            border: '1px solid var(--cc-line-strong)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--cc-mono)',
            color: 'var(--cc-muted)',
            transition: 'transform .25s',
            transform: open ? 'rotate(45deg)' : 'none',
          }}
        >
          +
        </span>
      </button>
      <div
        style={{
          overflow: 'hidden',
          maxHeight: open ? 200 : 0,
          transition: 'max-height .35s cubic-bezier(.2,.7,.2,1)',
        }}
      >
        <div
          style={{
            paddingBottom: 28,
            paddingLeft: 134,
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: 28,
          }}
        >
          <div>
            <Eyebrow>Fair odds</Eyebrow>
            <div className="serif tnum" style={{ fontSize: 28, fontStyle: 'italic', fontWeight: 600, marginTop: 4 }}>
              {v.fairOdds.toFixed(2)}
            </div>
          </div>
          <div>
            <Eyebrow>Book odds</Eyebrow>
            <div
              className="serif tnum"
              style={{ fontSize: 28, fontStyle: 'italic', fontWeight: 600, color: 'var(--cc-muted)', marginTop: 4 }}
            >
              {v.marketOdds.toFixed(2)}
            </div>
          </div>
          <div>
            <Eyebrow>Why</Eyebrow>
            <div
              style={{
                fontFamily: 'var(--cc-serif)',
                fontStyle: 'italic',
                fontSize: 16,
                lineHeight: 1.45,
                color: 'var(--cc-text)',
                marginTop: 4,
              }}
            >
              &quot;{reasonText}&quot;
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function PageFooter() {
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
  return (
    <footer
      style={{
        maxWidth: 980,
        margin: '48px auto 0',
        padding: '40px 40px 0',
        borderTop: '1px solid var(--cc-line)',
        display: 'flex',
        justifyContent: 'space-between',
        fontFamily: 'var(--cc-mono)',
        fontSize: 10,
        letterSpacing: '0.1em',
        color: 'var(--cc-muted)',
        textTransform: 'uppercase',
      }}
    >
      <span>CupCast · A model, not a tip sheet</span>
      <span>{today}</span>
    </footer>
  )
}
