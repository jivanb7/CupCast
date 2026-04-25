import { Link } from 'react-router-dom'
import TeamCrest from './TeamCrest'

/**
 * MatchRow — two-up split card (locked v1 design).
 *
 * Designed to be rendered in a 2-column grid by the parent. Each card has:
 *   header  → league tag · kickoff time / date
 *   teams   → home crest + name · VS / score · away name + crest
 *   prob    → 10px gradient bar (H green | D amber | A red), exact probabilities
 *   pcts    → "38% Home · 17% Draw · 45% Away" inline
 *   footer  → ◆ Pick: <team> <conf%>  ·  value chip / live chip / ✓-✗ for recent
 *
 * Variants: 'today' | 'upcoming' | 'recent'
 */

function pickTeamName(match, predictedResult) {
  if (predictedResult === 'H') return match.home_team_short_name || match.home_team_name
  if (predictedResult === 'A') return match.away_team_short_name || match.away_team_name
  if (predictedResult === 'D') return 'Draw'
  return null
}

function formatKickoffTime(utcTime, dateStr) {
  if (!utcTime || utcTime === 'nan' || utcTime === 'NaN') return null
  const d = dateStr || new Date().toISOString().slice(0, 10)
  const dt = new Date(`${d}T${utcTime}:00Z`)
  if (isNaN(dt.getTime())) return null
  return dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
}

function formatShortDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function pct(p) {
  if (p == null) return 0
  return Math.round(p * 100)
}

export default function MatchRow({ match, variant = 'today' }) {
  if (!match) return null

  const pred = match.prediction
  const isLive = match.status === 'live'
  const isCompleted = match.status === 'completed' || variant === 'recent'
  const wasCorrect = pred?.was_correct
  const homeWon = match.result === 'H'
  const awayWon = match.result === 'A'
  const showScore = isLive || isCompleted
  const kickoff = formatKickoffTime(match.kickoff_time, match.match_date)

  const pickTeam = pred ? pickTeamName(match, pred.predicted_result) : null
  const pctDisplay = pred?.confidence != null ? `${pct(pred.confidence)}%` : null

  // Build the gradient stops from real probabilities. p1 = end of H zone,
  // p2 = end of D zone. Defaults if probs missing → flat 33/33/34 split.
  const ph = pct(pred?.prob_home_win) || 33
  const pd = pct(pred?.prob_draw) || 33
  const pa = pct(pred?.prob_away_win) || 34
  const p1 = ph
  const p2 = ph + pd
  const probBarStyle = pred
    ? {
        background: `linear-gradient(90deg, #10b981 0% ${p1}%, #f59e0b ${p1}% ${p2}%, #ef4444 ${p2}% 100%)`,
      }
    : { background: 'rgba(255,255,255,0.06)' }

  // Card border: gold tint for value picks, green for live, neutral otherwise
  const cardClasses = [
    'group relative bg-card border rounded-[12px] px-4 py-3.5',
    'transition-all hover:bg-[#141d2f] cursor-pointer h-full flex flex-col',
    pred?.is_value_pick
      ? 'border-accent-gold/30 hover:border-accent-gold/50'
      : isLive
      ? 'border-accent-green/30'
      : 'border-border/40 hover:border-accent-gold/30',
  ].join(' ')

  return (
    <Link
      to={`/match/${match.id}`}
      aria-label={`${match.home_team_name} vs ${match.away_team_name}`}
      className="block"
    >
      <div className={cardClasses}>
        {/* Header: league · [VALUE chip if any] · time / LIVE / date.
            LIVE replaces the kickoff time in the right slot for in-play games. */}
        <div className="flex justify-between items-center mb-3 text-[10px] text-foreground-muted gap-2">
          <span className="inline-flex items-center gap-1.5 font-semibold tracking-[0.04em] truncate min-w-0">
            <span className="w-[5px] h-[5px] rounded-full bg-accent-gold flex-shrink-0" />
            {match.league_name}
          </span>
          <span className="flex items-center gap-2 flex-shrink-0">
            {pred?.is_value_pick && (
              <span className="inline-flex items-center px-1.5 py-[2px] rounded-md text-[9px] font-extrabold tracking-[0.06em] bg-accent-gold/12 text-accent-gold border border-accent-gold/30">
                ◆ VALUE
              </span>
            )}
            {isLive ? (
              <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9px] font-extrabold tracking-[0.06em] bg-accent-green/15 text-accent-green border border-accent-green/30">
                <span className="w-[4px] h-[4px] rounded-full bg-accent-green animate-pulse" />
                LIVE{match.match_minute ? ` ${match.match_minute}` : ''}
              </span>
            ) : (
              <span className="text-tabular">
                {variant === 'recent' ? formatShortDate(match.match_date) : kickoff || ''}
              </span>
            )}
          </span>
        </div>

        {/* Teams row */}
        <div className="flex items-center gap-2.5 mb-3">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <TeamCrest
              name={match.home_team_name}
              crestUrl={match.home_team_crest}
              countryCode={match.home_team_country_code}
              size="sm"
            />
            <span className="text-[13px] font-bold text-foreground truncate">
              {match.home_team_name}
            </span>
          </div>

          {showScore ? (
            <span className="text-[14px] font-extrabold text-tabular px-1 flex-shrink-0">
              <span className={homeWon ? 'text-accent-green' : 'text-foreground'}>
                {match.home_goals ?? '-'}
              </span>
              <span className="text-foreground-muted/60 mx-1">–</span>
              <span className={awayWon ? 'text-accent-green' : 'text-foreground'}>
                {match.away_goals ?? '-'}
              </span>
            </span>
          ) : (
            <span className="text-[10px] font-bold tracking-[0.2em] text-foreground-muted/60 flex-shrink-0">
              VS
            </span>
          )}

          <div className="flex items-center gap-2 flex-1 min-w-0 justify-end">
            <span className="text-[13px] font-bold text-foreground truncate text-right">
              {match.away_team_name}
            </span>
            <TeamCrest
              name={match.away_team_name}
              crestUrl={match.away_team_crest}
              countryCode={match.away_team_country_code}
              size="sm"
            />
          </div>
        </div>

        {/* Probability bar */}
        <div className="h-[10px] rounded-[5px] mb-1.5" style={probBarStyle} />

        {/* H / D / A percentages — green = home (H), amber = draw, red = away (A) */}
        {pred ? (
          <div className="flex justify-between text-[11px] text-tabular mb-3">
            <span className="text-accent-green font-bold truncate max-w-[40%]">
              {ph}% {match.home_team_short_name || match.home_team_name}{' '}
              <span className="text-accent-green/70 font-semibold">(H)</span>
            </span>
            <span className="text-accent-amber">{pd}% Draw</span>
            <span className="text-accent-red font-bold truncate max-w-[40%] text-right">
              {pa}% {match.away_team_short_name || match.away_team_name}{' '}
              <span className="text-accent-red/70 font-semibold">(A)</span>
            </span>
          </div>
        ) : (
          <div className="text-[11px] text-foreground-muted/70 mb-3">No prediction available</div>
        )}

        {/* Footer: pick + chips. Picked team is colored on the H/D/A
            spectrum so users can read the side at a glance. The % is
            pushed to the right, separated from the team name. */}
        <FooterRow
          variant={variant}
          pred={pred}
          pickTeam={pickTeam}
          pctDisplay={pctDisplay}
          wasCorrect={wasCorrect}
        />
      </div>
    </Link>
  )
}

/**
 * Footer renderer split out so the H/D/A → color mapping is colocated
 * with the spans that use it. Layout: [pick text on left] [% + chips on right]
 */
function FooterRow({ variant, pred, pickTeam, pctDisplay, wasCorrect }) {
  // Pick-side color matches the H/D/A spectrum so the user can tell
  // at a glance which side the model picked: green = home, amber = draw,
  // red = away. For 'recent' variant we override green/red by correctness.
  const pickColor =
    pred?.predicted_result === 'H' ? 'text-accent-green'
    : pred?.predicted_result === 'A' ? 'text-accent-red'
    : pred?.predicted_result === 'D' ? 'text-accent-amber'
    : 'text-foreground'

  const pctColor =
    variant === 'recent' && wasCorrect === true ? 'text-accent-green'
    : variant === 'recent' && wasCorrect === false ? 'text-accent-red'
    : pickColor

  return (
    <div className="mt-auto flex items-center justify-between gap-3 pt-2.5 border-t border-border/30">
      {/* Left: pick text */}
      <div className="flex items-center gap-1.5 text-[12px] min-w-0 flex-1">
        {variant === 'recent' && wasCorrect != null ? (
          <>
            <span
              className={`inline-flex items-center justify-center w-[18px] h-[18px] rounded-full text-[10px] font-extrabold flex-shrink-0 ${
                wasCorrect
                  ? 'bg-accent-green/15 text-accent-green border border-accent-green/40'
                  : 'bg-accent-red/15 text-accent-red border border-accent-red/40'
              }`}
              aria-label={wasCorrect ? 'Prediction correct' : 'Prediction wrong'}
            >
              {wasCorrect ? '✓' : '✗'}
            </span>
            <span className="text-foreground-muted/80">Predicted</span>
            {pickTeam && (
              <span className={`font-bold truncate ${pickColor}`}>{pickTeam}</span>
            )}
          </>
        ) : pickTeam ? (
          <>
            <span className="text-accent-gold font-extrabold flex-shrink-0">◆</span>
            <span className="text-foreground-muted/80">Pick:</span>
            <span className={`font-bold truncate ${pickColor}`}>{pickTeam}</span>
          </>
        ) : (
          <span className="text-foreground-muted/60">—</span>
        )}
      </div>

      {/* Right: confidence % standing alone — LIVE / VALUE chips
          live in the header now to keep the footer focused on the pick. */}
      <div className="flex items-center flex-shrink-0">
        {pctDisplay && (
          <span className={`text-[14px] font-extrabold text-tabular tracking-[-0.01em] ${pctColor}`}>
            {pctDisplay}
          </span>
        )}
      </div>
    </div>
  )
}
