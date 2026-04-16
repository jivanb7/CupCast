import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Sparkles, TrendingUp, Target, Zap, ArrowRight } from 'lucide-react'
import { getUpcomingMatches, getResults, getLeagues } from '../services/api'
import MatchCard from '../components/match/MatchCard'
import ProbabilityBar from '../components/match/ProbabilityBar'
import LeagueSelector from '../components/ui/LeagueSelector'
import LoadingSpinner from '../components/ui/LoadingSpinner'

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

function findSpotlightMatch(matches) {
  const now = new Date()
  const cutoff = new Date(now.getTime() + 3 * 24 * 60 * 60 * 1000)

  const candidates = matches.filter((m) => {
    if (!m.prediction) return false
    const matchDate = new Date(m.match_date + 'T00:00:00')
    return matchDate <= cutoff
  })

  if (candidates.length === 0) return null

  return candidates.reduce((best, m) => {
    const conf = m.prediction.confidence || 0
    const bestConf = best.prediction.confidence || 0
    return conf > bestConf ? m : best
  })
}

function KpiCard({ icon: Icon, label, value, subtext, accent = false }) {
  return (
    <div className="cc-stat-card">
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`w-4 h-4 ${accent ? 'text-accent-gold' : 'text-foreground-muted'}`} />
        <span className="cc-label">{label}</span>
      </div>
      <p className={`text-3xl font-bold text-tabular ${accent ? 'text-accent-gold' : 'text-foreground'}`}>
        {value}
      </p>
      {subtext && <p className="text-xs text-foreground-muted mt-1">{subtext}</p>}
    </div>
  )
}

export default function Dashboard() {
  const [leagues, setLeagues] = useState([])
  const [matches, setMatches] = useState([])
  const [results, setResults] = useState([])
  const [resultAccuracy, setResultAccuracy] = useState(null)
  const [selectedLeague, setSelectedLeague] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getLeagues()
      .then(setLeagues)
      .catch((err) => setError(err.message))
  }, [])

  const fetchData = useCallback((showSpinner = true) => {
    if (showSpinner) {
      setLoading(true)
      setError(null)
    }

    Promise.all([
      getUpcomingMatches(selectedLeague, 14),
      getResults(selectedLeague, 7),
    ])
      .then(([upcomingData, resultsData]) => {
        setMatches(upcomingData.matches || [])
        setResults(resultsData.matches || [])
        setResultAccuracy(resultsData.prediction_accuracy)
        setError(null)
        setLoading(false)
      })
      .catch((err) => {
        // On background refresh, keep last good data visible
        if (showSpinner) {
          setError(err.message)
        }
        setLoading(false)
      })
  }, [selectedLeague])

  useEffect(() => {
    fetchData(true)
    const interval = setInterval(() => fetchData(false), 60000)
    return () => clearInterval(interval)
  }, [fetchData])

  const spotlight = findSpotlightMatch(matches)
  const valuePicks = matches.filter(m => m.prediction?.is_value_pick).length

  // Compute today's accuracy (not all-time)
  const today = new Date().toLocaleDateString('en-CA')
  const todayResults = results.filter(m => m.match_date === today && m.prediction?.was_correct !== null && m.prediction?.was_correct !== undefined)
  const todayCorrect = todayResults.filter(m => m.prediction?.was_correct === true).length
  const todayAccuracy = todayResults.length > 0 ? Math.round((todayCorrect / todayResults.length) * 100) : null

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-24 pb-12">
      {/* Hero Spotlight */}
      {spotlight && (
        <Link to={`/match/${spotlight.id}`} className="block mb-8 group">
          <div className="cc-card-featured p-6 sm:p-8">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-4 h-4 text-accent-gold" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.15em] text-accent-gold">
                Featured Prediction
              </span>
              {spotlight.status === 'live' && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-accent-green/15 text-accent-green border border-accent-green/20">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-green animate-pulse" />
                  LIVE{spotlight.match_minute ? ` · ${spotlight.match_minute}` : ''}
                </span>
              )}
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-between gap-6 mb-6">
              <div className="text-center sm:text-left">
                <h2 className="text-h2 text-foreground">
                  <span className={
                    spotlight.status === 'completed' && spotlight.result === 'H' ? 'text-accent-green' :
                    spotlight.status !== 'completed' && spotlight.prediction?.predicted_result === 'H' ? 'text-accent-green' :
                    spotlight.status !== 'completed' && spotlight.prediction?.predicted_result === 'D' ? 'text-accent-amber' :
                    ''
                  }>
                    {spotlight.home_team_name}
                  </span>
                  {(spotlight.status === 'live' || spotlight.status === 'completed') && spotlight.home_goals != null ? (
                    <span className="mx-3">
                      <span className={spotlight.result === 'H' ? 'text-accent-green' : ''}>{spotlight.home_goals}</span>
                      <span className="text-foreground-muted mx-1">-</span>
                      <span className={spotlight.result === 'A' ? 'text-accent-green' : ''}>{spotlight.away_goals}</span>
                    </span>
                  ) : (
                    <span className="text-foreground-muted mx-3">vs</span>
                  )}
                  <span className={
                    spotlight.status === 'completed' && spotlight.result === 'A' ? 'text-accent-green' :
                    spotlight.status !== 'completed' && spotlight.prediction?.predicted_result === 'A' ? 'text-accent-red' :
                    spotlight.status !== 'completed' && spotlight.prediction?.predicted_result === 'D' ? 'text-accent-amber' :
                    ''
                  }>
                    {spotlight.away_team_name}
                  </span>
                </h2>
                <p className="text-sm text-foreground-muted mt-2">
                  {spotlight.league_name} &middot; {formatDate(spotlight.match_date)}
                  {spotlight.kickoff_time && formatKickoffTime(spotlight.kickoff_time) && (
                    <span> &middot; {formatKickoffTime(spotlight.kickoff_time)}</span>
                  )}
                </p>
              </div>

              {spotlight.prediction && (
                <div className="text-center flex-shrink-0">
                  <p className="cc-label mb-1">Confidence</p>
                  <p className="text-4xl font-bold text-accent-gold text-tabular">
                    {spotlight.prediction.confidence != null ? `${Math.round(spotlight.prediction.confidence * 100)}%` : '--'}
                  </p>
                </div>
              )}
            </div>

            {spotlight.prediction && (
              <ProbabilityBar
                probHome={spotlight.prediction.prob_home_win}
                probDraw={spotlight.prediction.prob_draw}
                probAway={spotlight.prediction.prob_away_win}
                predictedResult={spotlight.prediction.predicted_result}
                size="lg"
              />
            )}

            <div className="flex items-center gap-1 mt-4 text-sm text-foreground-muted group-hover:text-accent-gold transition-colors duration-200">
              View match details
              <ArrowRight className="w-4 h-4" />
            </div>
          </div>
        </Link>
      )}

      {/* KPI Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <KpiCard
          icon={TrendingUp}
          label="Upcoming Matches"
          value={matches.length}
        />
        <KpiCard
          icon={Target}
          label="Today's Accuracy"
          value={todayAccuracy != null ? `${todayAccuracy}%` : '--'}
          subtext={todayResults.length > 0 ? `${todayCorrect}/${todayResults.length} today` : 'No games evaluated yet'}
          accent
        />
        <KpiCard
          icon={Zap}
          label="Value Picks Found"
          value={valuePicks}
        />
      </div>

      {/* Section header + league selector */}
      <div className="mb-6">
        <h1 className="text-h1 mb-2">Upcoming Predictions</h1>
        <p className="text-sm text-foreground-muted mb-6">ML-powered match outcome predictions</p>
        <LeagueSelector
          leagues={leagues}
          selected={selectedLeague}
          onChange={setSelectedLeague}
        />
      </div>

      {/* Content */}
      <div>
        {loading && (
          <div className="flex justify-center py-20">
            <LoadingSpinner size="lg" label="Loading matches" />
          </div>
        )}
        {error && (
          <div className="cc-card p-8 text-center">
            <p className="text-accent-red">{error}</p>
          </div>
        )}
        {!loading && !error && (
          <>
            {/* Match Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {matches.map((match) => (
                <MatchCard key={match.id} match={match} />
              ))}
              {matches.length === 0 && (
                <div className="col-span-full cc-card p-12 text-center">
                  <p className="text-foreground-muted">No upcoming matches found.</p>
                </div>
              )}
            </div>

            {/* Recent Results */}
            {results.length > 0 && (
              <section className="mt-16">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-h2">Recent Results</h2>
                  {todayAccuracy != null && (
                    <span className="text-sm text-foreground-muted">
                      Today:{' '}
                      <span className="text-accent-green font-semibold text-tabular">
                        {todayAccuracy}%
                      </span>
                      <span className="text-foreground-muted/50 ml-2">
                        ({todayCorrect}/{todayResults.length})
                      </span>
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {results.slice(0, 6).map((match) => (
                    <MatchCard key={match.id} match={match} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}
