import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import CountryFlag from '../ui/CountryFlag'

/**
 * OpeningMatchPrediction — gold-bordered hero block for the very first WC fixture.
 *
 * Visually mirrors FeaturedPrediction (same gold gradient, same probability bar
 * + confidence layout) so the page reads as one design system. Differences:
 *   - Country flags instead of club crests (national-team page).
 *   - Probability bar labels are the team names, not Home/Draw/Away (matches
 *     the Match Detail decision).
 *   - Includes a one-sentence Elo-derived rationale below the bar.
 */

function buildKickoffDate(match) {
  if (!match?.match_date) return null
  const time = match.kickoff_time && match.kickoff_time !== 'nan' && match.kickoff_time !== 'NaN'
    ? match.kickoff_time
    : '12:00'
  const dt = new Date(`${match.match_date}T${time}:00Z`)
  return Number.isNaN(dt.getTime()) ? null : dt
}

function formatCountdown(ms) {
  if (ms <= 0) return 'kicks off now'
  const totalMin = Math.floor(ms / 60000)
  const days = Math.floor(totalMin / (60 * 24))
  const hours = Math.floor((totalMin % (60 * 24)) / 60)
  const mins = totalMin % 60
  if (days >= 1) return `kicks off in ${days}d ${hours}h`
  if (hours >= 1) return `kicks off in ${hours}h ${mins}m`
  return `kicks off in ${mins}m`
}

function formatLongDate(dt) {
  if (!dt) return ''
  return dt.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

export default function OpeningMatchPrediction({ data }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!data?.available || !data.match) return undefined
    const interval = setInterval(() => setNow(Date.now()), 60000)
    return () => clearInterval(interval)
  }, [data?.match?.id])

  if (!data || !data.available || !data.match) {
    return null
  }

  const match = data.match
  const pred = match.prediction
  const kickoffDate = buildKickoffDate(match)
  const countdown = kickoffDate ? formatCountdown(kickoffDate.getTime() - now) : null

  const homePct = Math.round((pred?.prob_home_win ?? 0) * 100)
  const drawPct = Math.round((pred?.prob_draw ?? 0) * 100)
  const awayPct = Math.round((pred?.prob_away_win ?? 0) * 100)
  const confidencePct = pred?.confidence != null ? Math.round(pred.confidence * 100) : null

  const homeName = match.home_team_name
  const awayName = match.away_team_name
  const homeShort = match.home_team_short_name || homeName
  const awayShort = match.away_team_short_name || awayName

  return (
    <Link
      to={`/match/${match.id}`}
      className="block group mt-6"
      aria-label={`Opening match: ${homeName} vs ${awayName}`}
    >
      <div
        className="relative rounded-[14px] px-6 py-5 sm:px-7 sm:py-6 overflow-hidden border border-accent-gold/30 bg-gradient-to-br from-accent-gold/[0.14] via-accent-gold/[0.03] to-transparent transition-colors group-hover:border-accent-gold/50"
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{ background: 'radial-gradient(circle at 85% 20%, rgba(245,158,11,0.12), transparent 50%)' }}
        />

        {/* header */}
        <div className="relative flex items-center justify-between mb-4 flex-wrap gap-2">
          <div className="flex items-center gap-1.5 text-accent-gold text-[11px] font-bold tracking-[0.18em] uppercase">
            <span>◆</span> Opening Match · FIFA World Cup 2026
          </div>
          <div className="text-[11px] text-foreground-muted">
            {formatLongDate(kickoffDate)}
            {countdown && (
              <>
                {' · '}
                <span className="inline-flex items-center gap-1.5 text-accent-gold font-semibold">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
                  {countdown}
                </span>
              </>
            )}
          </div>
        </div>

        {/* flags row */}
        <div className="relative grid [grid-template-columns:1fr_auto_1fr] items-center gap-4 sm:gap-5 mb-5">
          <div className="flex flex-col items-center gap-2.5">
            <CountryFlag
              code={match.home_team_country_code}
              size="lg"
              title={homeName}
            />
            <div className="text-sm font-bold text-center">{homeName}</div>
          </div>

          <div className="text-base font-semibold tracking-[0.18em] text-foreground-muted">VS</div>

          <div className="flex flex-col items-center gap-2.5">
            <CountryFlag
              code={match.away_team_country_code}
              size="lg"
              title={awayName}
            />
            <div className="text-sm font-bold text-center">{awayName}</div>
          </div>
        </div>

        {/* prob bar + confidence */}
        {pred && (
          <div className="relative grid [grid-template-columns:1fr_110px] gap-5 items-center">
            <div>
              <div
                className="h-2 rounded-full mb-2 relative overflow-hidden"
                role="img"
                aria-label={`${homeName} ${homePct}%, draw ${drawPct}%, ${awayName} ${awayPct}%`}
              >
                <div className="absolute inset-y-0 left-0" style={{ width: `${homePct}%`, background: '#22C55E' }} />
                <div className="absolute inset-y-0" style={{ left: `${homePct}%`, width: `${drawPct}%`, background: '#FBBF24' }} />
                <div className="absolute inset-y-0" style={{ left: `${homePct + drawPct}%`, width: `${awayPct}%`, background: '#EF4444' }} />
              </div>
              <div
                className="grid text-[11px] font-medium"
                style={{ gridTemplateColumns: `${homePct}% ${drawPct}% ${awayPct}%` }}
              >
                <div className="text-accent-green truncate">{homePct}% {homeShort}</div>
                <div className="text-accent-amber text-center">{drawPct}% Draw</div>
                <div className="text-accent-red text-right truncate">{awayPct}% {awayShort}</div>
              </div>
            </div>

            <div className="text-center">
              <div className="cc-label">Confidence</div>
              <div className="text-[34px] sm:text-[38px] leading-none font-extrabold text-accent-gold tracking-[-0.03em] text-tabular">
                {confidencePct != null ? `${confidencePct}%` : '--'}
              </div>
            </div>
          </div>
        )}

        {data.rationale && (
          <p className="relative mt-4 text-[12px] text-foreground-muted leading-relaxed">
            {data.rationale}
          </p>
        )}
      </div>
    </Link>
  )
}
