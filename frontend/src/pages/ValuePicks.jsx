import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Zap, SlidersHorizontal, AlertTriangle } from 'lucide-react'
import { getValuePicks } from '../services/api'
import ValuePickBadge from '../components/match/ValuePickBadge'
import LoadingSpinner from '../components/ui/LoadingSpinner'

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function ProbCell({ value, isEdge = false }) {
  const pct = Math.round((value ?? 0) * 100)
  const color = isEdge
    ? value > 0 ? 'text-accent-green' : value < 0 ? 'text-accent-red' : 'text-foreground-muted'
    : 'text-foreground'

  return (
    <span className={`text-tabular text-xs font-medium ${color}`}>
      {isEdge && value > 0 ? '+' : ''}
      {pct}%
    </span>
  )
}

export default function ValuePicks() {
  const [picks, setPicks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [minEdge, setMinEdge] = useState(0.08)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getValuePicks(null, minEdge)
      .then((data) => setPicks(Array.isArray(data) ? data : data?.picks || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [minEdge])

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-24 pb-12">
      {/* Page header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <Zap className="w-6 h-6 text-accent-gold" />
          <h1 className="text-h1">Value Picks</h1>
        </div>
        <p className="text-sm text-foreground-muted max-w-2xl">
          Matches where our model's probability differs from bookmaker implied probability
          by more than the selected threshold. A positive edge means the model thinks
          an outcome is more likely than the market does.
        </p>
      </div>

      {/* Edge threshold control */}
      <div className="cc-card p-4 mb-6 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="w-4 h-4 text-foreground-muted" />
          <label htmlFor="edge-slider" className="text-sm font-medium text-foreground">
            Min edge:
          </label>
        </div>
        <input
          id="edge-slider"
          type="range"
          min={0.05}
          max={0.20}
          step={0.01}
          value={minEdge}
          onChange={(e) => setMinEdge(parseFloat(e.target.value))}
          className="w-32 accent-accent-gold cursor-pointer"
        />
        <span className="text-accent-gold font-bold text-tabular text-lg">
          {Math.round(minEdge * 100)}%
        </span>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-20">
          <LoadingSpinner size="lg" label="Finding value picks" />
        </div>
      ) : error ? (
        <div className="cc-card p-8 text-center">
          <p className="text-accent-red">{error}</p>
        </div>
      ) : picks.length === 0 ? (
        <div className="cc-card p-12 text-center">
          <Zap className="w-8 h-8 text-foreground-muted mx-auto mb-3" />
          <p className="text-foreground-muted font-medium mb-1">No value picks found</p>
          <p className="text-sm text-foreground-muted/60">
            Try lowering the minimum edge threshold, or check back when predictions are generated.
          </p>
        </div>
      ) : (
        <div className="cc-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-deep/50">
                  <th className="text-left px-4 py-3 cc-label">Match</th>
                  <th className="text-left px-3 py-3 cc-label">League</th>
                  <th className="text-left px-3 py-3 cc-label">Date</th>
                  <th className="text-center px-3 py-3 cc-label" colSpan={3}>
                    Model (H/D/A)
                  </th>
                  <th className="text-center px-3 py-3 cc-label" colSpan={3}>
                    Market (H/D/A)
                  </th>
                  <th className="text-center px-3 py-3 cc-label">Edge</th>
                  <th className="text-center px-3 py-3 cc-label">Pick</th>
                </tr>
              </thead>
              <tbody>
                {picks.map((pick) => (
                  <tr
                    key={pick.match_id}
                    className="border-b border-white/5 hover:bg-white/[0.03] transition-colors duration-200"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/match/${pick.match_id}`}
                        className="text-foreground hover:text-accent-gold transition-colors duration-200 font-medium cursor-pointer"
                      >
                        {pick.home_team_name} vs {pick.away_team_name}
                      </Link>
                    </td>
                    <td className="px-3 py-3 text-foreground-muted text-xs">
                      {pick.league_name}
                    </td>
                    <td className="px-3 py-3 text-foreground-muted text-xs">
                      {formatDate(pick.match_date)}
                    </td>
                    <td className="px-2 py-3 text-center">
                      <ProbCell value={pick.model_prob_home} />
                    </td>
                    <td className="px-2 py-3 text-center">
                      <ProbCell value={pick.model_prob_draw} />
                    </td>
                    <td className="px-2 py-3 text-center">
                      <ProbCell value={pick.model_prob_away} />
                    </td>
                    <td className="px-2 py-3 text-center">
                      <ProbCell value={pick.bookmaker_prob_home} />
                    </td>
                    <td className="px-2 py-3 text-center">
                      <ProbCell value={pick.bookmaker_prob_draw} />
                    </td>
                    <td className="px-2 py-3 text-center">
                      <ProbCell value={pick.bookmaker_prob_away} />
                    </td>
                    <td className="px-3 py-3 text-center">
                      <span className="text-tabular text-sm font-bold text-accent-green">
                        +{Math.round(pick.max_edge * 100)}%
                      </span>
                    </td>
                    <td className="px-3 py-3 text-center">
                      <ValuePickBadge
                        direction={pick.value_pick_direction}
                        edge={pick.max_edge}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Disclaimer */}
      <div className="mt-8 cc-card p-4 border-accent-red/10">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-accent-red mt-0.5 flex-shrink-0" />
          <p className="text-xs text-foreground-muted leading-relaxed">
            Value picks indicate statistical disagreement between our model and bookmaker odds.
            They are not betting recommendations. Past model performance does not guarantee future results.
            Please gamble responsibly.
          </p>
        </div>
      </div>
    </div>
  )
}
