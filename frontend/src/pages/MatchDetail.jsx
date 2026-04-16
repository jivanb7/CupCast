import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Shield, Clock, BarChart3 } from 'lucide-react'
import { getMatch } from '../services/api'
import ProbabilityBar from '../components/match/ProbabilityBar'
import TeamForm from '../components/team/TeamForm'
import ValuePickBadge from '../components/match/ValuePickBadge'
import LoadingSpinner from '../components/ui/LoadingSpinner'

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function StatRow({ label, home, away }) {
  if (home == null && away == null) return null
  return (
    <div className="flex items-center justify-between py-3 border-b border-white/5 last:border-0">
      <span className="text-sm font-semibold text-foreground w-16 text-right text-tabular">{home ?? '-'}</span>
      <span className="text-xs text-foreground-muted flex-1 text-center uppercase tracking-wider">{label}</span>
      <span className="text-sm font-semibold text-foreground w-16 text-left text-tabular">{away ?? '-'}</span>
    </div>
  )
}

export default function MatchDetail() {
  const { matchId } = useParams()
  const [match, setMatch] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchMatch = useCallback((showSpinner = true) => {
    if (showSpinner) {
      setLoading(true)
      setError(null)
    }
    getMatch(matchId)
      .then((data) => {
        setMatch(data)
        setError(null)
      })
      .catch((err) => {
        // On background refresh, keep last good data visible
        if (showSpinner) {
          setError(err.message)
        }
      })
      .finally(() => setLoading(false))
  }, [matchId])

  useEffect(() => {
    fetchMatch(true)
    const interval = setInterval(() => fetchMatch(false), 30000)
    return () => clearInterval(interval)
  }, [fetchMatch])

  if (loading) {
    return (
      <div className="flex justify-center pt-32">
        <LoadingSpinner size="lg" label="Loading match" />
      </div>
    )
  }
  if (error) {
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

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 pt-24 pb-12">
      {/* Back link */}
      <Link
        to="/"
        className="inline-flex items-center gap-2 text-sm text-foreground-muted hover:text-foreground transition-colors duration-200 mb-6 cursor-pointer"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to matches
      </Link>

      {/* Match Header Card */}
      <div className="cc-card p-6 sm:p-8 mb-6">
        <div className="flex items-center justify-between mb-6">
          <span className="cc-label">{match.league_name}</span>
          <span className="flex items-center gap-1.5 text-xs text-foreground-muted">
            <Clock className="w-3.5 h-3.5" />
            {formatDate(match.match_date)}
          </span>
        </div>

        <div className="flex items-center justify-between my-6">
          <div className="text-center flex-1">
            <p className="text-xl sm:text-2xl font-bold text-foreground">{match.home_team_name}</p>
            <p className="cc-label mt-2">Home</p>
          </div>

          {match.status === 'completed' ? (
            <div className="text-center px-6">
              <p className="text-4xl sm:text-5xl font-bold text-tabular">
                {match.home_goals ?? '-'}
                <span className="text-foreground-muted mx-2">-</span>
                {match.away_goals ?? '-'}
              </p>
              <p className="cc-label mt-2">Full Time</p>
            </div>
          ) : (
            <div className="text-center px-6">
              <p className="text-2xl font-bold text-foreground-muted">vs</p>
              <p className="cc-label mt-2">Scheduled</p>
            </div>
          )}

          <div className="text-center flex-1">
            <p className="text-xl sm:text-2xl font-bold text-foreground">{match.away_team_name}</p>
            <p className="cc-label mt-2">Away</p>
          </div>
        </div>

        {pred && pred.is_value_pick && (
          <div className="flex justify-center mt-4">
            <ValuePickBadge direction={pred.value_pick_direction} />
          </div>
        )}
      </div>

      {/* Prediction Section */}
      {pred && (
        <div className="cc-card p-6 sm:p-8 mb-6">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-accent-blue" />
              <h2 className="text-lg font-semibold text-foreground">Prediction</h2>
            </div>
            <span className="text-sm text-foreground-muted">
              Confidence{' '}
              <span className="text-accent-gold font-bold text-tabular">
                {pred.confidence != null ? `${Math.round(pred.confidence * 100)}%` : '--'}
              </span>
            </span>
          </div>

          <ProbabilityBar
            probHome={pred.prob_home_win}
            probDraw={pred.prob_draw}
            probAway={pred.prob_away_win}
            predictedResult={pred.predicted_result}
            size="lg"
          />

          {/* Predicted outcome + result */}
          <div className="mt-6 flex flex-col items-center gap-3">
            <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/5">
              <span className="text-sm text-foreground-muted">Predicted:</span>
              <span className="text-sm font-semibold text-foreground">
                {pred.predicted_result === 'H'
                  ? `${match.home_team_name} Win`
                  : pred.predicted_result === 'A'
                  ? `${match.away_team_name} Win`
                  : 'Draw'}
              </span>
            </span>

            {/* Prediction result badge */}
            {pred.was_correct === true && (
              <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-accent-green/10 border border-accent-green/20">
                <span className="text-accent-green text-lg">✓</span>
                <span className="text-sm font-semibold text-accent-green">Prediction Correct</span>
              </span>
            )}
            {pred.was_correct === false && (
              <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-accent-red/10 border border-accent-red/20">
                <span className="text-accent-red text-lg">✗</span>
                <span className="text-sm font-semibold text-accent-red">
                  Prediction Wrong{match.result ? ` — Actual: ${match.result === 'H' ? 'Home Win' : match.result === 'A' ? 'Away Win' : 'Draw'}` : ''}
                </span>
              </span>
            )}
          </div>

          {/* SHAP explanation */}
          {pred.explanation_text && (
            <div className="mt-6 p-4 rounded-card bg-deep border border-border/50">
              <div className="flex items-center gap-2 mb-2">
                <Shield className="w-4 h-4 text-accent-purple" />
                <p className="cc-label text-accent-purple">Why this prediction</p>
              </div>
              <p className="text-sm text-foreground-muted leading-relaxed">
                {pred.explanation_text}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Match Stats — only show if we have at least one stat */}
      {match.status === 'completed' && (match.home_shots != null || match.home_corners != null) && (
        <div className="cc-card p-6 sm:p-8 mb-6">
          <h2 className="text-lg font-semibold mb-4">Match Stats</h2>
          <StatRow label="Shots" home={match.home_shots} away={match.away_shots} />
          <StatRow label="On Target" home={match.home_shots_on_target} away={match.away_shots_on_target} />
          <StatRow label="Corners" home={match.home_corners} away={match.away_corners} />
        </div>
      )}

      {/* Team Form */}
      {(match.home_form || match.away_form) && (
        <section className="mb-6">
          <h2 className="text-lg font-semibold mb-4">Team Form (Last 5)</h2>
          <TeamForm homeForm={match.home_form} awayForm={match.away_form} />
        </section>
      )}

      {/* Head-to-Head */}
      {match.h2h_last_5 && match.h2h_last_5.length > 0 && (
        <div className="cc-card p-6 sm:p-8">
          <h2 className="text-lg font-semibold mb-4">Head-to-Head (Last 5 Meetings)</h2>
          <div className="space-y-0">
            {match.h2h_last_5.map((h2h) => (
              <div
                key={h2h.id}
                className="flex items-center justify-between py-3 border-b border-white/5 last:border-0 hover:bg-white/[0.02] transition-colors duration-200"
              >
                <span className="text-sm flex-1 text-right font-medium text-foreground">
                  {h2h.home_team_name}
                </span>
                <span className="text-sm font-bold px-4 min-w-[60px] text-center text-tabular text-foreground">
                  {h2h.home_goals != null
                    ? `${h2h.home_goals} - ${h2h.away_goals}`
                    : '-'}
                </span>
                <span className="text-sm flex-1 text-left font-medium text-foreground">
                  {h2h.away_team_name}
                </span>
                <span className="text-xs text-foreground-muted ml-4 w-24 text-right">
                  {h2h.match_date}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
