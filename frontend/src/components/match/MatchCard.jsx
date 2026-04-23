import { Link } from 'react-router-dom'
import { Calendar, ChevronRight, CheckCircle2, XCircle, Clock } from 'lucide-react'
import ProbabilityBar from './ProbabilityBar'
import ValuePickBadge from './ValuePickBadge'

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

function formatKickoffTime(utcTime) {
  if (!utcTime || utcTime === 'nan' || utcTime === 'NaN') return null
  const today = new Date().toISOString().slice(0, 10)
  const utcDate = new Date(`${today}T${utcTime}:00Z`)
  if (isNaN(utcDate.getTime())) return null
  return utcDate.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZoneName: 'short' })
}

function resultLabel(result) {
  if (result === 'H') return 'Home Win'
  if (result === 'A') return 'Away Win'
  if (result === 'D') return 'Draw'
  return ''
}

function PredictionBadge({ wasCorrect }) {
  if (wasCorrect === null || wasCorrect === undefined) return null

  if (wasCorrect) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-accent-green/15 text-accent-green border border-accent-green/20">
        <CheckCircle2 className="w-3 h-3" />
        Correct
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-accent-red/15 text-accent-red border border-accent-red/20">
      <XCircle className="w-3 h-3" />
      Wrong
    </span>
  )
}

export default function MatchCard({ match }) {
  if (!match) return null

  const isCompleted = match.status === 'completed'
  const isLive = match.status === 'live'
  const hasScore = isCompleted || isLive
  const pred = match.prediction

  return (
    <Link to={`/match/${match.id}`} className="block group">
      <div className="cc-card-interactive p-4 flex flex-col min-h-[180px]">
        {/* Header row: league + status */}
        <div className="flex items-center justify-between mb-1">
          <span className="cc-label text-[11px] truncate max-w-[140px]">{match.league_name}</span>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {isLive && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-accent-green/15 text-accent-green border border-accent-green/20">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-green animate-pulse" />
                LIVE{match.match_minute ? ` · ${match.match_minute}` : ''}
              </span>
            )}
            {isCompleted && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-foreground-muted/10 text-foreground-muted">
                FT
              </span>
            )}
            {pred?.was_correct !== null && pred?.was_correct !== undefined && (
              <PredictionBadge wasCorrect={pred.was_correct} />
            )}
            {pred?.is_value_pick && <ValuePickBadge />}
          </div>
        </div>
        {/* Date + time row */}
        <div className="flex items-center gap-1 text-[11px] text-foreground-muted mb-3">
          <Calendar className="w-3 h-3" />
          {formatDate(match.match_date)}
          {match.kickoff_time && (
            <span className="ml-1 text-foreground-muted/70">· {formatKickoffTime(match.kickoff_time)}</span>
          )}
        </div>

        {/* Teams row with score */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex-1 min-w-0 flex items-center gap-1.5">
            {match.home_team_crest && (
              <img src={match.home_team_crest} alt="" className="w-5 h-5 flex-shrink-0" loading="lazy" />
            )}
            <p className={`text-sm font-semibold truncate ${
              isCompleted && match.result === 'H' ? 'text-accent-green' :
              !isCompleted && pred?.predicted_result === 'H' ? 'text-accent-green' :
              !isCompleted && pred?.predicted_result === 'D' ? 'text-accent-amber' :
              'text-foreground'
            }`}>
              {match.home_team_name}
            </p>
          </div>

          {hasScore ? (
            <div className="flex items-center gap-2 px-4">
              <span className={`text-xl font-bold text-tabular ${
                match.result === 'H' ? 'text-accent-green' : 'text-foreground'
              }`}>
                {match.home_goals ?? '-'}
              </span>
              <span className={`text-xs ${isLive ? 'text-accent-green animate-pulse' : 'text-foreground-muted'}`}>-</span>
              <span className={`text-xl font-bold text-tabular ${
                match.result === 'A' ? 'text-accent-green' : 'text-foreground'
              }`}>
                {match.away_goals ?? '-'}
              </span>
            </div>
          ) : (
            <span className="px-4 text-[11px] font-medium text-foreground-muted uppercase tracking-wider">
              vs
            </span>
          )}

          <div className="flex-1 min-w-0 flex items-center gap-1.5 justify-end">
            <p className={`text-sm font-semibold truncate ${
              isCompleted && match.result === 'A' ? 'text-accent-green' :
              !isCompleted && pred?.predicted_result === 'A' ? 'text-accent-red' :
              !isCompleted && pred?.predicted_result === 'D' ? 'text-accent-amber' :
              'text-foreground'
            }`}>
              {match.away_team_name}
            </p>
            {match.away_team_crest && (
              <img src={match.away_team_crest} alt="" className="w-5 h-5 flex-shrink-0" loading="lazy" />
            )}
          </div>
        </div>

        {/* Result summary for completed matches */}
        {isCompleted && pred && (
          <div className="flex items-center justify-between mb-3 px-2 py-1.5 rounded-md bg-white/[0.03]">
            <span className="text-[11px] text-foreground-muted">
              Predicted:{' '}
              <span className="font-medium text-foreground">
                {pred.predicted_result === 'H' ? match.home_team_name :
                 pred.predicted_result === 'A' ? match.away_team_name : 'Draw'}
              </span>
            </span>
            <span className="text-[11px] text-foreground-muted">
              Actual:{' '}
              <span className={`font-medium ${
                match.result === 'D' ? 'text-accent-amber' : 'text-accent-green'
              }`}>
                {resultLabel(match.result)}
              </span>
            </span>
          </div>
        )}

        {/* Probability bar */}
        {pred && (
          <ProbabilityBar
            probHome={pred.prob_home_win}
            probDraw={pred.prob_draw}
            probAway={pred.prob_away_win}
            predictedResult={pred.predicted_result}
            size="sm"
          />
        )}

        {/* Bookmaker odds row — only shown when odds have been stamped by odds_service */}
        {pred && pred.odds_home != null && pred.odds_draw != null && pred.odds_away != null && (
          <div className="flex items-center justify-between mt-2 px-2 py-1 rounded-md bg-white/[0.02] text-[10px] text-foreground-muted text-tabular">
            <span>H <span className="text-foreground">{pred.odds_home.toFixed(2)}</span></span>
            <span>D <span className="text-foreground">{pred.odds_draw.toFixed(2)}</span></span>
            <span>A <span className="text-foreground">{pred.odds_away.toFixed(2)}</span></span>
          </div>
        )}

        {/* Completed match without prediction */}
        {isCompleted && !pred && match.result && (
          <div className="text-center mt-2">
            <span className={`text-xs font-medium ${
              match.result === 'H' ? 'text-accent-green' :
              match.result === 'A' ? 'text-accent-red' :
              'text-accent-amber'
            }`}>
              {resultLabel(match.result)}
            </span>
          </div>
        )}

        {/* Confidence + arrow footer */}
        {pred && (
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/5">
            <span className="text-[11px] text-foreground-muted">
              Confidence{' '}
              <span className="text-accent-gold font-semibold text-tabular">
                {pred.confidence != null ? `${Math.round(pred.confidence * 100)}%` : '--'}
              </span>
            </span>
            <ChevronRight className="w-4 h-4 text-foreground-muted group-hover:text-accent-gold transition-colors duration-200" />
          </div>
        )}
      </div>
    </Link>
  )
}
