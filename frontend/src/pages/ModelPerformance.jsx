import { useState, useEffect } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid,
} from 'recharts'
import { Target, Activity, TrendingDown, Clock, Cpu, Calendar, Hash, CheckCircle2, XCircle } from 'lucide-react'
import { getModelPerformance, getDailyPredictions } from '../services/api'
import LoadingSpinner from '../components/ui/LoadingSpinner'

function KpiCard({ icon: Icon, label, value, subtext, color = 'text-foreground' }) {
  return (
    <div className="cc-stat-card">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4 text-foreground-muted" />
        <span className="cc-label">{label}</span>
      </div>
      <p className={`text-3xl font-bold text-tabular ${color}`}>{value}</p>
      {subtext && <p className="text-xs text-foreground-muted mt-2">{subtext}</p>}
    </div>
  )
}

function CustomDot({ cx, cy, payload, onClick }) {
  if (payload.total === 0) return null
  return (
    <circle
      cx={cx}
      cy={cy}
      r={6}
      fill="#F59E0B"
      stroke="#0E1223"
      strokeWidth={2}
      className="cursor-pointer hover:r-8 transition-all"
      onClick={() => onClick(payload)}
    />
  )
}

function MatchResult({ match }) {
  const isCorrect = match.was_correct
  return (
    <div className={`flex items-center justify-between p-3 rounded-lg border ${
      isCorrect ? 'border-accent-green/20 bg-accent-green/5' : 'border-accent-red/20 bg-accent-red/5'
    }`}>
      <div className="flex items-center gap-3">
        {isCorrect ? (
          <CheckCircle2 className="w-4 h-4 text-accent-green flex-shrink-0" />
        ) : (
          <XCircle className="w-4 h-4 text-accent-red flex-shrink-0" />
        )}
        <div>
          <p className="text-sm font-medium text-foreground">
            {match.home_team}{' '}
            <span className="text-foreground-muted">
              {match.home_goals}-{match.away_goals}
            </span>{' '}
            {match.away_team}
          </p>
          <p className="text-[11px] text-foreground-muted">{match.league}</p>
        </div>
      </div>
      <div className="text-right">
        <p className="text-[11px] text-foreground-muted">
          Predicted: <span className="font-medium text-foreground">
            {match.predicted_result === 'H' ? match.home_team :
             match.predicted_result === 'A' ? match.away_team : 'Draw'}
          </span>
        </p>
        <p className="text-[11px] text-foreground-muted">
          Confidence: <span className="text-accent-gold font-medium">
            {match.confidence != null ? `${Math.round(match.confidence * 100)}%` : '--'}
          </span>
        </p>
      </div>
    </div>
  )
}

export default function ModelPerformance() {
  const [perf, setPerf] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedDay, setSelectedDay] = useState(null)
  const [dayMatches, setDayMatches] = useState(null)
  const [dayLoading, setDayLoading] = useState(false)

  useEffect(() => {
    getModelPerformance()
      .then(setPerf)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const handleDayClick = (dayData) => {
    if (selectedDay === dayData.rawDate) {
      setSelectedDay(null)
      setDayMatches(null)
      return
    }
    setSelectedDay(dayData.rawDate)
    setDayLoading(true)
    getDailyPredictions(dayData.rawDate)
      .then(setDayMatches)
      .catch(() => setDayMatches(null))
      .finally(() => setDayLoading(false))
  }

  if (loading) {
    return (
      <div className="flex justify-center pt-32">
        <LoadingSpinner size="lg" label="Loading metrics" />
      </div>
    )
  }
  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 pt-24">
        <div className="cc-card p-8 text-center">
          <p className="text-accent-red">{error}</p>
        </div>
      </div>
    )
  }
  if (!perf) return null

  // Build cumulative accuracy line data
  const dailyRaw = perf.accuracy_by_date || []
  let cumCorrect = 0
  let cumTotal = 0
  const chartData = dailyRaw.map((d) => {
    cumCorrect += d.correct
    cumTotal += d.total
    return {
      rawDate: d.date,
      date: new Date(d.date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      dailyAccuracy: Math.round(d.accuracy * 100),
      cumulativeAccuracy: cumTotal > 0 ? Math.round((cumCorrect / cumTotal) * 100) : 0,
      correct: d.correct,
      wrong: d.wrong,
      total: d.total,
      cumCorrect,
      cumTotal,
    }
  })

  const hasData = perf.total_predictions > 0

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-24 pb-12">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <Activity className="w-6 h-6 text-accent-blue" />
          <h1 className="text-h1">Model Performance</h1>
        </div>
        <p className="text-sm text-foreground-muted">
          How our model is performing on real matches. Full transparency.
        </p>
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <KpiCard
          icon={Target}
          label="Overall Accuracy"
          value={hasData ? `${Math.round(perf.overall_accuracy * 100)}%` : '--'}
          subtext={hasData ? `${perf.correct_predictions} / ${perf.total_predictions}` : 'No evaluated predictions yet'}
          color="text-accent-gold"
        />
        <KpiCard
          icon={Activity}
          label="F1 Score (Macro)"
          value={perf.overall_f1_macro != null ? perf.overall_f1_macro.toFixed(3) : '--'}
          color="text-accent-blue"
        />
        <KpiCard
          icon={TrendingDown}
          label="Log-Loss"
          value={perf.overall_log_loss != null ? perf.overall_log_loss.toFixed(3) : '--'}
          color="text-accent-purple"
        />
        <KpiCard
          icon={Clock}
          label="Last 30 Days"
          value={
            perf.accuracy_last_30_days != null
              ? `${Math.round(perf.accuracy_last_30_days * 100)}%`
              : '--'
          }
          subtext="Rolling accuracy"
          color="text-accent-green"
        />
      </div>

      {/* Model Info */}
      <div className="cc-card p-6 mb-8">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Cpu className="w-3.5 h-3.5 text-foreground-muted" />
              <p className="cc-label">Model Version</p>
            </div>
            <p className="text-sm font-medium text-foreground">{perf.model_version}</p>
          </div>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Calendar className="w-3.5 h-3.5 text-foreground-muted" />
              <p className="cc-label">Last Trained</p>
            </div>
            <p className="text-sm font-medium text-foreground">
              {perf.last_trained
                ? new Date(perf.last_trained).toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                  })
                : 'Not yet trained'}
            </p>
          </div>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Hash className="w-3.5 h-3.5 text-foreground-muted" />
              <p className="cc-label">Total Evaluated</p>
            </div>
            <p className="text-sm font-medium text-foreground text-tabular">
              {(perf.total_predictions ?? 0).toLocaleString()}
            </p>
          </div>
        </div>
      </div>

      {/* Accuracy Chart */}
      {chartData.length > 0 && (
        <div className="cc-card p-6 mb-8">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold">Prediction Accuracy Over Time</h2>
            <p className="text-xs text-foreground-muted">Click a point to see match details</p>
          </div>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 10, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" />
                <XAxis
                  dataKey="date"
                  tick={{ fill: '#94A3B8', fontSize: 11 }}
                  axisLine={{ stroke: '#334155' }}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: '#94A3B8', fontSize: 11 }}
                  axisLine={{ stroke: '#334155' }}
                  tickLine={false}
                  unit="%"
                />
                <ReferenceLine
                  y={33}
                  stroke="#475569"
                  strokeDasharray="6 4"
                  label={{ value: 'Random (33%)', position: 'right', fill: '#64748B', fontSize: 10 }}
                />
                <ReferenceLine
                  y={50}
                  stroke="#475569"
                  strokeDasharray="6 4"
                  label={{ value: 'Bookmaker (~50%)', position: 'right', fill: '#64748B', fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0E1223',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    fontSize: '12px',
                  }}
                  labelStyle={{ color: '#F8FAFC', fontWeight: 600 }}
                  formatter={(value, name, props) => {
                    const d = props.payload
                    if (name === 'cumulativeAccuracy') {
                      return [`${value}% (${d.cumCorrect}/${d.cumTotal} total)`, 'Cumulative']
                    }
                    return [`${value}% (${d.correct}/${d.total})`, 'Daily']
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="cumulativeAccuracy"
                  stroke="#F59E0B"
                  strokeWidth={2.5}
                  dot={<CustomDot onClick={handleDayClick} />}
                  activeDot={{ r: 8, fill: '#F59E0B', stroke: '#FEF3C7', strokeWidth: 2 }}
                />
                <Line
                  type="monotone"
                  dataKey="dailyAccuracy"
                  stroke="#3B82F6"
                  strokeWidth={1.5}
                  strokeDasharray="5 5"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="flex items-center gap-6 mt-4 text-xs text-foreground-muted">
            <span className="flex items-center gap-2">
              <span className="w-4 h-0.5 bg-accent-gold inline-block" /> Cumulative accuracy
            </span>
            <span className="flex items-center gap-2">
              <span className="w-4 h-0.5 bg-accent-blue inline-block" style={{ borderTop: '2px dashed #3B82F6', height: 0 }} /> Daily accuracy
            </span>
          </div>
        </div>
      )}

      {/* Drill-down: Selected Day's Matches */}
      {selectedDay && (
        <div className="cc-card p-6 mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">
              {new Date(selectedDay + 'T00:00:00').toLocaleDateString('en-US', {
                weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
              })}
            </h2>
            {dayMatches && (
              <span className="text-sm text-foreground-muted">
                <span className="text-accent-green font-semibold">{dayMatches.correct}</span> correct,{' '}
                <span className="text-accent-red font-semibold">{dayMatches.wrong}</span> wrong
                {' '}({Math.round(dayMatches.accuracy * 100)}%)
              </span>
            )}
          </div>

          {dayLoading ? (
            <div className="flex justify-center py-8">
              <LoadingSpinner size="sm" label="Loading matches" />
            </div>
          ) : dayMatches?.matches?.length > 0 ? (
            <div className="space-y-2">
              {dayMatches.matches.map((m) => (
                <MatchResult key={m.match_id} match={m} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-foreground-muted text-center py-4">No evaluated predictions for this date.</p>
          )}
        </div>
      )}

      {/* No data state */}
      {!hasData && (
        <div className="cc-card p-12 text-center mb-8">
          <Target className="w-8 h-8 text-foreground-muted mx-auto mb-3" />
          <p className="text-foreground-muted font-medium mb-1">No evaluated predictions yet</p>
          <p className="text-sm text-foreground-muted/60">
            Performance metrics will populate once predictions are generated and matches are completed.
          </p>
        </div>
      )}

      {/* Understanding the Numbers */}
      <div className="cc-card p-6">
        <h2 className="text-lg font-semibold mb-4">Understanding the Numbers</h2>
        <div className="space-y-4 text-sm text-foreground-muted leading-relaxed">
          <p>
            <strong className="text-foreground">Accuracy</strong> measures how often the model
            correctly predicts the match outcome. A baseline model that always predicts the most
            common outcome would achieve roughly 45% accuracy.
          </p>
          <p>
            <strong className="text-foreground">F1 Score (Macro)</strong> balances precision and
            recall across all three outcome classes. Draws are much rarer than wins, making them
            the hardest outcome to predict correctly.
          </p>
          <p>
            <strong className="text-foreground">Log-Loss</strong> measures how well-calibrated
            the model's probabilities are. Lower is better. A model saying "60% home win"
            should see home wins happen roughly 60% of the time in those situations.
          </p>
        </div>
      </div>
    </div>
  )
}
