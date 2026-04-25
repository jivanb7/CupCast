import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { getMatch } from '../services/api'
import TeamCrest from '../components/match/TeamCrest'
import FormBadge from '../components/match/FormBadge'
import LoadingSpinner from '../components/ui/LoadingSpinner'

/**
 * MatchDetail — match-detail-v1 visual style.
 *
 * Preserves the adaptive polling behaviour of the previous version:
 *   live      → 15s
 *   completed → 300s (occasional refresh in case ratings settle)
 *   else      → 60s
 */

function formatLongDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

function formatKickoff(utcTime, dateStr) {
  if (!utcTime || utcTime === 'nan' || utcTime === 'NaN') return null
  const d = dateStr || new Date().toISOString().slice(0, 10)
  const dt = new Date(`${d}T${utcTime}:00Z`)
  if (isNaN(dt.getTime())) return null
  return dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZoneName: 'short' })
}

function buildKickoffDate(match) {
  if (!match?.match_date) return null
  const time = match.kickoff_time && match.kickoff_time !== 'nan' && match.kickoff_time !== 'NaN'
    ? match.kickoff_time : '12:00'
  const dt = new Date(`${match.match_date}T${time}:00Z`)
  return isNaN(dt.getTime()) ? null : dt
}

function formatCountdown(ms) {
  if (ms <= 0) return null
  const totalMin = Math.floor(ms / 60000)
  const days = Math.floor(totalMin / (60 * 24))
  const hours = Math.floor((totalMin % (60 * 24)) / 60)
  const mins = totalMin % 60
  if (days >= 1) return `kicks in ${days}d ${hours}h`
  if (hours >= 1) return `kicks in ${hours}h ${mins}m`
  return `kicks in ${mins}m`
}

function FormStrip({ results }) {
  if (!results?.length) return null
  return <FormBadge results={results} />
}

function H2HRow({ row }) {
  // Determine winner (with team_id we can colour the winning side)
  let winner = null
  if (row.home_goals != null && row.away_goals != null) {
    if (row.home_goals > row.away_goals) winner = 'home'
    else if (row.away_goals > row.home_goals) winner = 'away'
    else winner = 'draw'
  }

  return (
    <div className="grid [grid-template-columns:1fr_70px_1fr_90px] items-center py-2.5 border-b border-white/5 last:border-0 text-xs gap-2">
      <span className={`text-right font-semibold truncate ${winner === 'home' ? 'text-accent-green' : 'text-foreground'}`}>
        {row.home_team_name}
      </span>
      <span className={`text-center text-sm font-extrabold text-tabular ${
        winner === 'draw' ? 'text-accent-amber'
        : winner === 'home' || winner === 'away' ? 'text-foreground'
        : 'text-foreground-muted'
      }`}>
        {row.home_goals != null && row.away_goals != null
          ? `${row.home_goals} – ${row.away_goals}` : '–'}
      </span>
      <span className={`text-left font-semibold truncate ${winner === 'away' ? 'text-accent-green' : 'text-foreground'}`}>
        {row.away_team_name}
      </span>
      <span className="text-right text-foreground-muted text-[11px]">
        {formatLongDate(row.match_date)}
      </span>
    </div>
  )
}

function FormList({ form, label, match, isHome }) {
  if (!form) {
    return (
      <div className="rounded-[14px] border border-white/6 bg-card px-6 py-5">
        <div className="text-[15px] font-bold mb-3.5 tracking-[-0.01em]">Last 5 — {label}</div>
        <p className="text-sm text-foreground-muted">No form data available.</p>
      </div>
    )
  }
  const winRate = Math.round((form.win_rate_5 ?? 0) * 100)
  const last5 = form.last_5_results || []
  const wCount = last5.filter((r) => r === 'W').length
  const dCount = last5.filter((r) => r === 'D').length
  const lCount = last5.filter((r) => r === 'L').length

  return (
    <div className="rounded-[14px] border border-white/6 bg-card px-6 py-5">
      <div className="flex items-center justify-between mb-3.5">
        <div className="text-[15px] font-bold tracking-[-0.01em]">Last 5 — {label}</div>
      </div>
      <div className="flex items-center gap-2 mb-2.5 text-[13px] font-bold">
        <TeamCrest
          name={form.team_name}
          crestUrl={isHome ? match.home_team_crest : match.away_team_crest}
          countryCode={isHome ? match.home_team_country_code : match.away_team_country_code}
          size="xs"
        />
        <span>{form.team_name}</span>
        <span className="ml-auto text-[11px] text-foreground-muted font-medium">
          {wCount}W · {dCount}D · {lCount}L
        </span>
      </div>
      <div className="flex flex-col gap-2 mt-1.5">
        <FormStrip results={last5} />
        <div className="text-[11px] text-foreground-muted">
          Win rate <span className={`font-semibold text-tabular ${
            winRate >= 60 ? 'text-accent-green' : winRate >= 40 ? 'text-accent-amber' : 'text-accent-red'
          }`}>{winRate}%</span>
          {' '}· Scored <span className="text-foreground text-tabular">
            {form.goals_scored_avg_5 != null ? `${form.goals_scored_avg_5.toFixed(1)}` : '--'}
          </span>/g
          {' '}· Conceded <span className="text-foreground text-tabular">
            {form.goals_conceded_avg_5 != null ? `${form.goals_conceded_avg_5.toFixed(1)}` : '--'}
          </span>/g
        </div>
      </div>
    </div>
  )
}

export default function MatchDetail() {
  const { matchId } = useParams()
  const [match, setMatch] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [now, setNow] = useState(() => Date.now())
  const [refreshedAt, setRefreshedAt] = useState(null)

  const fetchMatch = useCallback((showSpinner = true) => {
    if (showSpinner) {
      setLoading(true)
      setError(null)
    }
    getMatch(matchId)
      .then((data) => {
        setMatch(data)
        setRefreshedAt(Date.now())
        setError(null)
      })
      .catch((err) => {
        if (showSpinner) setError(err.message)
      })
      .finally(() => setLoading(false))
  }, [matchId])

  useEffect(() => {
    fetchMatch(true)
  }, [fetchMatch])

  useEffect(() => {
    if (!match) return undefined
    const pollMs =
      match.status === 'live' ? 15000
      : match.status === 'completed' ? 300000
      : 60000
    const interval = setInterval(() => fetchMatch(false), pollMs)
    return () => clearInterval(interval)
  }, [match?.status, fetchMatch])

  // 60s tick for the kickoff countdown + "refreshed Xs ago"
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 30000)
    return () => clearInterval(interval)
  }, [])

  if (loading && !match) {
    return (
      <div className="flex justify-center pt-32">
        <LoadingSpinner size="lg" label="Loading match" />
      </div>
    )
  }
  if (error && !match) {
    return (
      <div className="max-w-4xl mx-auto px-4 pt-24">
        <div className="cc-card p-8 text-center">
          <p className="text-accent-red">{error}</p>
        </div>
      </div>
    )
  }
  if (!match) return null

  const pred = match.prediction
  const isLive = match.status === 'live'
  const isCompleted = match.status === 'completed'
  const isScheduled = !isLive && !isCompleted

  const kickoffDate = buildKickoffDate(match)
  const countdown = isScheduled && kickoffDate ? formatCountdown(kickoffDate.getTime() - now) : null
  const kickoffStr = formatKickoff(match.kickoff_time, match.match_date)

  const homePct = pred ? Math.round((pred.prob_home_win ?? 0) * 100) : 0
  const drawPct = pred ? Math.round((pred.prob_draw ?? 0) * 100) : 0
  const awayPct = pred ? Math.round((pred.prob_away_win ?? 0) * 100) : 0
  const confidencePct = pred?.confidence != null ? Math.round(pred.confidence * 100) : null

  const predictedTeamName = pred?.predicted_result === 'H'
    ? match.home_team_name
    : pred?.predicted_result === 'A' ? match.away_team_name
    : 'Draw'

  const refreshedAgo = refreshedAt ? Math.max(0, Math.round((now - refreshedAt) / 1000)) : null

  return (
    <div className="max-w-[1180px] mx-auto px-4 sm:px-6 lg:px-12 pt-24 pb-12">
      <Link
        to="/matches"
        className="inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-accent-gold transition-colors mb-4"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to matches
      </Link>

      {/* HERO */}
      <div className="relative overflow-hidden rounded-[16px] px-6 py-7 sm:px-8 sm:py-7 mb-3.5 border border-accent-gold/[0.28] bg-gradient-to-br from-accent-gold/[0.12] via-accent-gold/[0.02] to-transparent">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{ background: 'radial-gradient(circle at 90% 10%, rgba(245,158,11,0.10), transparent 55%)' }}
        />

        {/* meta row */}
        <div className="relative flex justify-between items-center mb-5 text-xs flex-wrap gap-2">
          <div className="flex items-center gap-2.5 text-foreground-muted">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border border-white/8 bg-white/5 text-foreground">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-gold" />
              {match.league_name}
            </span>
            {match.tournament && <span>{match.tournament}</span>}
          </div>
          <div className="flex items-center gap-2.5">
            {kickoffStr && <span className="text-foreground-muted">{formatLongDate(match.match_date)} · {kickoffStr}</span>}
            {isLive && (
              <span className="inline-flex items-center gap-1.5 text-accent-green font-semibold text-xs">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-green animate-pulse" />
                LIVE{match.match_minute ? ` · ${match.match_minute}` : ''}
              </span>
            )}
            {countdown && (
              <span className="inline-flex items-center gap-1.5 text-accent-gold font-semibold text-xs">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-gold animate-pulse" />
                {countdown}
              </span>
            )}
          </div>
        </div>

        {/* crests row */}
        <div className="relative grid [grid-template-columns:1fr_auto_1fr] items-center gap-5 mb-5">
          <div className="flex flex-col items-center gap-3">
            <TeamCrest
              name={match.home_team_name}
              crestUrl={match.home_team_crest}
              countryCode={match.home_team_country_code}
              size="xl"
            />
            <div className="text-[20px] font-extrabold tracking-[-0.01em] text-center">
              {match.home_team_name}
            </div>
            <div className="text-[11px] text-foreground-muted text-center">Home</div>
            {match.home_form?.last_5_results?.length > 0 && (
              <FormStrip results={match.home_form.last_5_results} />
            )}
          </div>

          <div className="flex flex-col items-center gap-1.5 min-w-[80px]">
            {(isLive || isCompleted) ? (
              <div className="flex items-baseline gap-2 text-[40px] font-extrabold tracking-[-0.03em] text-tabular leading-none">
                <span className={match.result === 'H' ? 'text-accent-green' : 'text-foreground'}>
                  {match.home_goals ?? '-'}
                </span>
                <span className="text-foreground-muted text-2xl">–</span>
                <span className={match.result === 'A' ? 'text-accent-green' : 'text-foreground'}>
                  {match.away_goals ?? '-'}
                </span>
              </div>
            ) : (
              <div className="text-[22px] text-foreground-muted font-bold tracking-[0.2em]">VS</div>
            )}
            <div className="text-[11px] text-foreground-muted">
              {isCompleted ? 'Full time' : isLive ? `${match.match_minute || ''}` : 'Scheduled'}
            </div>
          </div>

          <div className="flex flex-col items-center gap-3">
            <TeamCrest
              name={match.away_team_name}
              crestUrl={match.away_team_crest}
              countryCode={match.away_team_country_code}
              size="xl"
            />
            <div className="text-[20px] font-extrabold tracking-[-0.01em] text-center">
              {match.away_team_name}
            </div>
            <div className="text-[11px] text-foreground-muted text-center">Away</div>
            {match.away_form?.last_5_results?.length > 0 && (
              <FormStrip results={match.away_form.last_5_results} />
            )}
          </div>
        </div>

        {/* Bottom: value pick + completed verdict */}
        {(pred?.is_value_pick || isCompleted) && (
          <div className="relative flex justify-center items-center gap-2.5 pt-4 border-t border-accent-gold/15 flex-wrap">
            {isCompleted && pred?.was_correct === true && (
              <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold bg-accent-green/12 border border-accent-green/40 text-accent-green">
                ✓ Prediction Correct
              </span>
            )}
            {isCompleted && pred?.was_correct === false && (
              <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold bg-accent-red/12 border border-accent-red/40 text-accent-red">
                ✗ Prediction Wrong{match.result ? ` — Actual: ${match.result === 'D' ? 'Draw' : match.result === 'H' ? match.home_team_name : match.away_team_name}` : ''}
              </span>
            )}
            {pred?.is_value_pick && (
              <>
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-bold tracking-[0.1em] uppercase bg-accent-gold/12 border border-accent-gold/40 text-accent-gold">
                  ◆ Value Pick
                </span>
                <span className="text-foreground-muted text-xs">
                  Model sees positive EV on{' '}
                  <b className="text-foreground font-semibold">
                    {pred.value_pick_direction === 'H' ? match.home_team_name
                      : pred.value_pick_direction === 'A' ? match.away_team_name
                      : 'Draw'}
                  </b>
                </span>
              </>
            )}
          </div>
        )}
      </div>

      {/* PREDICTION */}
      {pred && (
        <div className="rounded-[14px] border border-white/6 bg-card px-6 py-5 sm:px-7 mb-3.5">
          <div className="flex justify-between items-center mb-3.5">
            <div className="text-[15px] font-bold tracking-[-0.01em]">Prediction</div>
            <div className="text-[11px] text-foreground-muted">Powered by ML model</div>
          </div>

          <div className="grid [grid-template-columns:1fr_140px] gap-7 items-center max-md:grid-cols-1 max-md:gap-4">
            <div>
              {/* prob bar */}
              <div className="relative h-3.5 rounded-[7px] overflow-hidden mb-2.5">
                <div className="absolute inset-y-0 left-0" style={{ width: `${homePct}%`, background: '#22C55E' }} />
                <div className="absolute inset-y-0" style={{ left: `${homePct}%`, width: `${drawPct}%`, background: '#FBBF24' }} />
                <div className="absolute inset-y-0" style={{ left: `${homePct + drawPct}%`, width: `${awayPct}%`, background: '#EF4444' }} />
              </div>
              <div
                className="grid text-[12px] font-semibold gap-1"
                style={{ gridTemplateColumns: `${Math.max(homePct, 12)}% ${Math.max(drawPct, 12)}% ${Math.max(awayPct, 12)}%` }}
              >
                <div className="text-accent-green truncate" title={match.home_team_name}>{homePct}% {match.home_team_name}</div>
                <div className="text-accent-amber text-center">{drawPct}% Draw</div>
                <div className="text-accent-red text-right truncate" title={match.away_team_name}>{awayPct}% {match.away_team_name}</div>
              </div>
            </div>

            <div className="text-center rounded-[12px] border border-accent-gold/30 bg-accent-gold/[0.08] px-2 py-3.5">
              <div className="text-[42px] font-extrabold text-accent-gold tracking-[-0.03em] leading-none text-tabular">
                {confidencePct != null ? `${confidencePct}%` : '--'}
              </div>
              <div className="text-[10px] tracking-[0.18em] uppercase text-foreground-muted font-bold mt-1">Confidence</div>
            </div>
          </div>

          <div className="mt-4 px-4 py-3.5 rounded-[10px] bg-accent-green/[0.08] border border-accent-green/25 flex items-center gap-3 flex-wrap">
            <span className="w-2 h-2 rounded-full bg-accent-green flex-shrink-0" />
            <span className="text-[11px] tracking-[0.12em] uppercase font-semibold text-foreground-muted">Predicted winner</span>
            <span className="text-[15px] font-bold text-accent-green">{predictedTeamName}</span>
          </div>

          {pred.explanation_text && (
            <div className="mt-4 px-5 py-3.5 rounded-[10px] bg-base border border-white/6">
              <div className="flex items-center gap-1.5 text-[10px] tracking-[0.18em] uppercase font-bold text-accent-purple mb-2">
                ◆ Why this prediction
              </div>
              <p className="text-[13px] leading-relaxed text-foreground/90">
                {pred.explanation_text}
              </p>
            </div>
          )}
        </div>
      )}

      {/* ODDS */}
      {pred && (
        <div className="rounded-[14px] border border-white/6 bg-card px-6 py-5 sm:px-7 mb-3.5">
          <div className="flex justify-between items-center mb-2.5 flex-wrap gap-2">
            <div className="flex items-center gap-2 text-[15px] font-bold tracking-[-0.01em]">
              <span className="text-accent-gold">◆</span> Bookmaker Odds + Model Edge
            </div>
            <span className="text-[11px] text-foreground-muted">Bet365 via API-Football</span>
          </div>

          {pred.odds_home != null && pred.odds_draw != null && pred.odds_away != null ? (
            <>
              <p className="text-[11px] text-foreground-muted leading-relaxed mb-3.5">
                Decimal odds from Bet365.{' '}
                <b className="text-foreground font-semibold">Market</b> is what the book thinks (1 ÷ odds).{' '}
                <b className="text-foreground font-semibold">Model</b> is our probability.{' '}
                <b className="text-foreground font-semibold">Edge</b> is model − market — positive means we see value.
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                {[
                  { key: 'H', sub: 'Home', team: match.home_team_name, odds: pred.odds_home, prob: pred.prob_home_win, edge: pred.edge_home, color: 'green' },
                  { key: 'D', sub: 'Draw', team: 'Tie', odds: pred.odds_draw, prob: pred.prob_draw, edge: pred.edge_draw, color: 'amber' },
                  { key: 'A', sub: 'Away', team: match.away_team_name, odds: pred.odds_away, prob: pred.prob_away_win, edge: pred.edge_away, color: 'red' },
                ].map((c) => {
                  const implied = 1 / c.odds
                  const modelProb = c.prob ?? 0
                  const edgeVal = c.edge != null ? c.edge : modelProb - implied
                  const isPick = pred.predicted_result === c.key

                  const borderColor =
                    c.color === 'green' ? 'border-accent-green/45'
                    : c.color === 'amber' ? 'border-accent-amber/45'
                    : 'border-accent-red/45'
                  const subColor =
                    c.color === 'green' ? 'text-accent-green'
                    : c.color === 'amber' ? 'text-accent-amber'
                    : 'text-accent-red'

                  return (
                    <div
                      key={c.key}
                      className={`relative rounded-[12px] border bg-base px-4 py-3.5 ${
                        isPick ? borderColor : 'border-white/6'
                      }`}
                    >
                      {isPick && (
                        <span className="absolute top-2.5 right-2.5 text-[9px] tracking-[0.1em] font-bold rounded-full px-2 py-0.5 bg-accent-gold/15 text-accent-gold">
                          OUR PICK
                        </span>
                      )}
                      <div className={`text-[10px] tracking-[0.2em] uppercase font-bold ${
                        isPick ? subColor : 'text-foreground-muted'
                      }`}>
                        {c.sub}
                      </div>
                      <div className="text-[13px] font-bold mt-0.5 truncate" title={c.team}>{c.team}</div>
                      <div className="text-[28px] font-extrabold mt-2 tracking-[-0.03em] text-tabular">{c.odds.toFixed(2)}</div>
                      <div className="text-[11px] text-foreground-muted mt-1 text-tabular">
                        Market: <b className="text-foreground font-semibold">{Math.round(implied * 100)}%</b>
                      </div>
                      <div className="text-[11px] text-foreground-muted text-tabular">
                        Model: <b className="text-foreground font-semibold">{Math.round(modelProb * 100)}%</b>
                      </div>
                      <div className={`text-[12px] font-bold mt-2.5 pt-2 border-t border-white/6 text-tabular ${
                        edgeVal > 0 ? 'text-accent-green' : 'text-foreground-muted'
                      }`}>
                        Edge: {edgeVal > 0 ? '+' : ''}{(edgeVal * 100).toFixed(1)}%
                      </div>
                    </div>
                  )
                })}
              </div>

              {pred.is_value_pick && (
                <div className="mt-3.5 px-3.5 py-3 rounded-[10px] bg-accent-gold/[0.08] border border-accent-gold/30 flex items-center gap-2.5 text-xs text-foreground/90 flex-wrap">
                  <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-[11px] font-bold tracking-[0.1em] uppercase bg-accent-gold/12 border border-accent-gold/40 text-accent-gold flex-shrink-0">
                    ◆ Value Pick
                  </span>
                  <span>
                    Edge clears our 8% threshold on{' '}
                    <b className="text-accent-gold font-bold">
                      {pred.value_pick_direction === 'H' ? match.home_team_name
                        : pred.value_pick_direction === 'A' ? match.away_team_name
                        : 'Draw'}
                    </b>
                    .
                  </span>
                </div>
              )}
            </>
          ) : (
            <div className="rounded-[10px] bg-base border border-white/6 px-5 py-5 text-center">
              <p className="text-sm text-foreground-muted">Bookmaker odds not yet published.</p>
              <p className="text-xs text-foreground-muted/70 mt-1">
                Sportsbooks typically price lines within ~14 days of kickoff.
              </p>
            </div>
          )}
        </div>
      )}

      {/* MATCH STATS (live + completed) */}
      {(isLive || isCompleted) && (match.home_shots != null || match.home_corners != null) && (
        <div className="rounded-[14px] border border-white/6 bg-card px-6 py-5 sm:px-7 mb-3.5">
          <div className="text-[15px] font-bold tracking-[-0.01em] mb-3.5">Match Stats</div>
          {[
            ['Shots', match.home_shots, match.away_shots],
            ['On Target', match.home_shots_on_target, match.away_shots_on_target],
            ['Corners', match.home_corners, match.away_corners],
          ].map(([label, h, a]) => (
            <div key={label} className="flex items-center justify-between py-2.5 border-b border-white/5 last:border-0">
              <span className="text-sm font-semibold w-16 text-right text-tabular">{h ?? '-'}</span>
              <span className="text-xs text-foreground-muted flex-1 text-center uppercase tracking-wider">{label}</span>
              <span className="text-sm font-semibold w-16 text-left text-tabular">{a ?? '-'}</span>
            </div>
          ))}
        </div>
      )}

      {/* TEAM FORM */}
      {(match.home_form || match.away_form) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 mb-3.5">
          <FormList form={match.home_form} label="Home" match={match} isHome />
          <FormList form={match.away_form} label="Away" match={match} isHome={false} />
        </div>
      )}

      {/* H2H */}
      {match.h2h_last_5 && match.h2h_last_5.length > 0 && (
        <div className="rounded-[14px] border border-white/6 bg-card px-6 py-5 sm:px-7 mb-3.5">
          <div className="flex justify-between items-center mb-3.5 flex-wrap gap-2">
            <div className="text-[15px] font-bold tracking-[-0.01em]">Head-to-Head — Last 5 Meetings</div>
            <span className="text-[11px] text-foreground-muted font-medium">
              {match.h2h_last_5.length} meetings
            </span>
          </div>
          <div>
            {match.h2h_last_5.map((row) => <H2HRow key={row.id} row={row} />)}
          </div>
        </div>
      )}

      {/* footer */}
      <div className="rounded-[10px] border border-white/6 bg-base px-5 py-3.5 text-xs text-foreground-muted flex justify-between items-center flex-wrap gap-2">
        <span>
          Data refreshed {refreshedAgo != null ? `${refreshedAgo}s ago` : 'just now'}
          {' · '}
          auto-polling every {match.status === 'live' ? '15s' : match.status === 'completed' ? '5m' : '60s'}
        </span>
        <span>
          Match ID <b className="text-foreground font-semibold">{match.id}</b>
        </span>
      </div>
    </div>
  )
}
