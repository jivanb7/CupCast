import { TrendingUp, TrendingDown, Target } from 'lucide-react'
import FormBadge from '../match/FormBadge'

function StatRow({ icon: Icon, label, value, className = '' }) {
  return (
    <div className="flex items-center justify-between py-2">
      <div className="flex items-center gap-2">
        <Icon className="w-3.5 h-3.5 text-foreground-muted" />
        <span className="text-sm text-foreground-muted">{label}</span>
      </div>
      <span className={`text-sm font-medium text-tabular ${className}`}>{value}</span>
    </div>
  )
}

function FormCard({ form, label }) {
  if (!form) {
    return (
      <div className="cc-card p-6 flex items-center justify-center">
        <p className="text-foreground-muted text-sm">No form data</p>
      </div>
    )
  }

  const winRate = Math.round((form.win_rate_5 || 0) * 100)

  return (
    <div className="cc-card p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-foreground">{form.team_name}</h3>
        <span className="cc-label">{label}</span>
      </div>

      <div className="mb-4">
        <FormBadge results={form.last_5_results || []} />
      </div>

      <div className="space-y-0 divide-y divide-white/5">
        <StatRow
          icon={TrendingUp}
          label="Scored"
          value={form.goals_scored_avg_5 != null ? `${form.goals_scored_avg_5.toFixed(1)}/game` : '--'}
          className="text-foreground"
        />
        <StatRow
          icon={TrendingDown}
          label="Conceded"
          value={form.goals_conceded_avg_5 != null ? `${form.goals_conceded_avg_5.toFixed(1)}/game` : '--'}
          className="text-foreground"
        />
        <StatRow
          icon={Target}
          label="Win rate"
          value={`${winRate}%`}
          className={winRate >= 60 ? 'text-accent-green' : winRate >= 40 ? 'text-accent-amber' : 'text-accent-red'}
        />
      </div>
    </div>
  )
}

export default function TeamForm({ homeForm, awayForm }) {
  if (!homeForm && !awayForm) return null

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <FormCard form={homeForm} label="Home" />
      <FormCard form={awayForm} label="Away" />
    </div>
  )
}
