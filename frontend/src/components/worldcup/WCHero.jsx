import { useEffect, useState } from 'react'
import CountryFlag from '../ui/CountryFlag'

/**
 * WCHero — gold-tinted tournament hero panel.
 *
 * Renders tournament name, tagline, host nations, four stat tiles,
 * and a live-ticking countdown to the next match (or to kickoff
 * pre-tournament).
 *
 * Props:
 *   overview: response from GET /api/v1/world-cup/overview
 */

function buildKickoff(iso) {
  if (!iso) return null
  const dt = new Date(iso)
  return Number.isNaN(dt.getTime()) ? null : dt
}

function formatCountdown(ms) {
  if (ms <= 0) return 'kicking off now'
  const totalMin = Math.floor(ms / 60000)
  const days = Math.floor(totalMin / (60 * 24))
  const hours = Math.floor((totalMin % (60 * 24)) / 60)
  const mins = totalMin % 60
  if (days >= 1) return `${days}d ${hours}h`
  if (hours >= 1) return `${hours}h ${mins}m`
  return `${mins}m`
}

function formatDateRange(start, end) {
  if (!start || !end) return ''
  const s = new Date(`${start}T00:00:00`)
  const e = new Date(`${end}T00:00:00`)
  const sm = s.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const em = e.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  return `${sm} → ${em}`
}

export default function WCHero({ overview }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(interval)
  }, [])

  if (!overview) return null

  const kickoff = buildKickoff(overview.next_match_kickoff)
  const isPreTournament =
    overview.matches_played === 0 &&
    overview.start_date &&
    new Date() < new Date(`${overview.start_date}T00:00:00`)

  const accuracyPct = overview.model_accuracy_wc != null
    ? `${Math.round(overview.model_accuracy_wc * 100)}%`
    : '—'

  const teamsTotal = 48 // FIFA WC 2026 expanded format

  return (
    <div
      className="relative overflow-hidden rounded-[18px] border border-accent-gold/30 px-6 sm:px-9 py-7 sm:py-8 mb-3.5"
      style={{
        background: `
          radial-gradient(circle at 85% 20%, rgba(245,158,11,0.18), transparent 55%),
          radial-gradient(circle at 10% 85%, rgba(245,158,11,0.08), transparent 50%),
          linear-gradient(135deg, rgba(245,158,11,0.12) 0%, rgba(11,18,32,0.6) 65%)
        `,
      }}
    >
      {/* WC26 watermark */}
      <span
        aria-hidden
        className="pointer-events-none absolute select-none font-black leading-none"
        style={{
          top: -40,
          right: -10,
          fontSize: 160,
          color: 'rgba(245,158,11,0.04)',
          letterSpacing: '-0.05em',
        }}
      >
        WC26
      </span>

      <div className="relative">
        <div className="inline-flex items-center gap-2 px-3 py-1 mb-3.5 rounded-full text-[10px] font-bold tracking-[0.2em] uppercase text-accent-gold border border-accent-gold/40 bg-accent-gold/15">
          <span aria-hidden>◆</span> FIFA World Cup 2026
        </div>

        <h1
          className="font-black tracking-[-0.03em] leading-none mb-2.5 text-[36px] sm:text-[44px]"
          style={{
            background: 'linear-gradient(135deg, #fff 0%, #F59E0B 100%)',
            WebkitBackgroundClip: 'text',
            backgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}
        >
          {overview.tournament_name || 'The 48-Nation Cup'}
        </h1>

        <p className="text-sm text-[#c7cdd8] mb-2 max-w-[640px] leading-[1.55]">
          First tournament of the expanded format. 16 host cities across three countries,
          104 matches over 39 days. Our model tracks every fixture — live standings, value
          picks, and a running projection of the bracket.
        </p>
        <p
          className="text-[11px] text-foreground-muted mb-5 max-w-[640px] leading-[1.45]"
          title="CupCast rates each team using historical international match results, then simulates the tournament many times. Win % reflects the share of simulations in which a team lifts the trophy."
        >
          Powered by the CupCast team ratings model.
        </p>

        <div className="grid lg:grid-cols-[auto_1fr_auto] gap-7 items-center">
          {/* Hosts */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] tracking-[0.18em] text-foreground-muted font-bold uppercase">
              Host nations
            </span>
            <div className="flex flex-wrap gap-x-2 gap-y-1.5 items-center">
              {(overview.host_countries || []).map((host) => (
                <span key={host.country_code} className="inline-flex items-center gap-1.5">
                  <CountryFlag code={host.country_code} size="md" title={host.name} />
                  <span className="text-xs font-semibold text-foreground">{host.name}</span>
                </span>
              ))}
            </div>
            <div className="text-[11px] text-foreground-muted mt-0.5">
              {formatDateRange(overview.start_date, overview.end_date)} · 16 cities · {overview.matches_total} matches
            </div>
          </div>

          {/* Stat tiles */}
          <div className="grid grid-cols-4 gap-3.5">
            <StatTile label="Teams" value={teamsTotal} />
            <StatTile label="Played" value={overview.matches_played ?? 0} gold />
            <StatTile label="Remaining" value={overview.matches_remaining ?? 0} />
            <StatTile label="Model acc." value={accuracyPct} gold />
          </div>

          {/* Countdown */}
          <div className="rounded-[12px] border border-accent-gold/25 bg-black/30 px-4 py-3.5 text-right min-w-[220px]">
            <div className="text-[10px] tracking-[0.15em] uppercase font-bold text-foreground-muted mb-1">
              {isPreTournament ? 'Tournament starts' : 'Next match'}
            </div>
            <div className="flex items-center justify-end gap-2 text-[22px] font-extrabold text-accent-gold tracking-[-0.02em]">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" aria-hidden />
              {kickoff
                ? formatCountdown(kickoff.getTime() - now)
                : isPreTournament
                ? 'Soon'
                : 'TBD'}
            </div>
            <div className="text-[11px] text-foreground-muted mt-1">
              {isPreTournament
                ? `Kicks off ${kickoff ? kickoff.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''}`
                : kickoff
                ? kickoff.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
                : 'No upcoming match scheduled'}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function StatTile({ label, value, gold = false }) {
  return (
    <div className="text-center">
      <div className={`text-[26px] font-extrabold tracking-[-0.02em] text-tabular ${gold ? 'text-accent-gold' : 'text-foreground'}`}>
        {value}
      </div>
      <div className="text-[10px] text-foreground-muted tracking-[0.15em] uppercase font-bold mt-0.5">
        {label}
      </div>
    </div>
  )
}
