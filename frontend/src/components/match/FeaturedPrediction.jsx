import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import TeamCrest from './TeamCrest'
import FormBadge from './FormBadge'

/**
 * FeaturedPrediction — gold-bordered hero block on the dashboard.
 * Mirrors the "Featured Prediction" card in dashboard-v2.html.
 *
 * Includes a live ticking countdown to kickoff (client-side
 * setInterval, every 60s — no backend traffic).
 */

function buildKickoffDate(match) {
  if (!match?.match_date) return null
  const time = match.kickoff_time && match.kickoff_time !== 'nan' && match.kickoff_time !== 'NaN'
    ? match.kickoff_time
    : '12:00'
  const dt = new Date(`${match.match_date}T${time}:00Z`)
  return isNaN(dt.getTime()) ? null : dt
}

function formatCountdown(ms) {
  if (ms <= 0) return 'kicks off now'
  const totalMin = Math.floor(ms / 60000)
  const days = Math.floor(totalMin / (60 * 24))
  const hours = Math.floor((totalMin % (60 * 24)) / 60)
  const mins = totalMin % 60
  if (days >= 1) return `kicks in ${days}d ${hours}h`
  if (hours >= 1) return `kicks in ${hours}h ${mins}m`
  return `kicks in ${mins}m`
}

function formatDateLabel(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

export default function FeaturedPrediction({ match }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!match) return undefined
    const interval = setInterval(() => setNow(Date.now()), 60000)
    return () => clearInterval(interval)
  }, [match?.id])

  if (!match) {
    return (
      <div className="rounded-[14px] px-6 py-6 mb-5 border border-accent-gold/20 bg-gradient-to-br from-accent-gold/[0.08] via-accent-gold/[0.02] to-transparent text-center">
        <div className="text-[11px] font-bold tracking-[0.18em] text-accent-gold uppercase mb-2">◆ Featured Prediction</div>
        <p className="text-sm text-foreground-muted">No featured predictions today — check back tomorrow.</p>
      </div>
    )
  }

  const pred = match.prediction
  const kickoffDate = buildKickoffDate(match)
  const countdown = kickoffDate ? formatCountdown(kickoffDate.getTime() - now) : null

  const homePct = Math.round((pred?.prob_home_win ?? 0) * 100)
  const drawPct = Math.round((pred?.prob_draw ?? 0) * 100)
  const awayPct = Math.round((pred?.prob_away_win ?? 0) * 100)
  const confidencePct = pred?.confidence != null ? Math.round(pred.confidence * 100) : null

  return (
    <Link
      to={`/match/${match.id}`}
      className="block group"
      aria-label={`Featured prediction: ${match.home_team_name} vs ${match.away_team_name}`}
    >
      <div
        className="relative rounded-[14px] px-6 py-5 sm:px-7 sm:py-6 mb-5 overflow-hidden border border-accent-gold/30 bg-gradient-to-br from-accent-gold/[0.14] via-accent-gold/[0.03] to-transparent transition-colors group-hover:border-accent-gold/50"
      >
        {/* radial decoration */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{ background: 'radial-gradient(circle at 85% 20%, rgba(245,158,11,0.12), transparent 50%)' }}
        />

        {/* header */}
        <div className="relative flex items-center justify-between mb-4 flex-wrap gap-2">
          <div className="flex items-center gap-1.5 text-accent-gold text-[11px] font-bold tracking-[0.18em] uppercase">
            <span>◆</span> Featured Prediction
          </div>
          <div className="text-[11px] text-foreground-muted">
            {match.league_name} · {formatDateLabel(match.match_date)}
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

        {/* crests row */}
        <div className="relative grid [grid-template-columns:1fr_auto_1fr] items-center gap-4 sm:gap-5 mb-5">
          {/* HOME */}
          <div className="flex flex-col items-center gap-2.5">
            <TeamCrest
              name={match.home_team_name}
              crestUrl={match.home_team_crest}
              countryCode={match.home_team_country_code}
              size="lg"
            />
            <div className="text-sm font-bold text-center">
              {match.home_team_name}
            </div>
            {match.home_form?.last_5_results?.length > 0 && (
              <FormBadge results={match.home_form.last_5_results} />
            )}
          </div>

          <div className="text-base font-semibold tracking-[0.18em] text-foreground-muted">VS</div>

          {/* AWAY */}
          <div className="flex flex-col items-center gap-2.5">
            <TeamCrest
              name={match.away_team_name}
              crestUrl={match.away_team_crest}
              countryCode={match.away_team_country_code}
              size="lg"
            />
            <div className="text-sm font-bold text-center">
              {match.away_team_name}
            </div>
            {match.away_form?.last_5_results?.length > 0 && (
              <FormBadge results={match.away_form.last_5_results} />
            )}
          </div>
        </div>

        {/* prob bar + confidence */}
        {pred && (
          <div className="relative grid [grid-template-columns:1fr_110px] gap-5 items-center">
            <div>
              <div
                className="h-2 rounded-full mb-2 relative overflow-hidden"
                role="img"
                aria-label={`Home ${homePct}%, draw ${drawPct}%, away ${awayPct}%`}
              >
                <div className="absolute inset-y-0 left-0" style={{ width: `${homePct}%`, background: '#22C55E' }} />
                <div className="absolute inset-y-0" style={{ left: `${homePct}%`, width: `${drawPct}%`, background: '#FBBF24' }} />
                <div className="absolute inset-y-0" style={{ left: `${homePct + drawPct}%`, width: `${awayPct}%`, background: '#EF4444' }} />
              </div>
              <div className="grid text-[11px] font-medium" style={{ gridTemplateColumns: `${homePct}% ${drawPct}% ${awayPct}%` }}>
                <div className="text-accent-green truncate">{homePct}% {match.home_team_short_name || match.home_team_name}</div>
                <div className="text-accent-amber text-center">{drawPct}% Draw</div>
                <div className="text-accent-red text-right truncate">{awayPct}% {match.away_team_short_name || match.away_team_name}</div>
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
      </div>
    </Link>
  )
}
