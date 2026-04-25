import CountryFlag from '../ui/CountryFlag'

/**
 * GroupCard — single group standings table with qualification visual language:
 *   green left-border = advancing (top 2)
 *   amber left-border = best-third candidate
 *   red left-border   = eliminated
 *   gray              = still live
 *
 * Props:
 *   group: { label, venue, teams: [...], next_fixtures: [...] }
 */

// API returns `live` pre-tournament; `advancing` / `third-place` / `eliminated`
// once results land. We accept the snake_case `best_third` alias as well so
// either backend convention renders correctly.
const STATUS_BORDER_COLOR = {
  advancing: '#10b981',
  'third-place': '#f59e0b',
  best_third: '#f59e0b',
  eliminated: '#ef4444',
  live: 'rgba(255,255,255,0.1)',
}

// Days within which a short "Thu 7:00 PM" label is unambiguous. Anything
// further out gets the absolute month+day so users can't read "Thu" as
// "this Thursday" when kickoff is actually weeks away.
const SHORT_FORMAT_HORIZON_DAYS = 7

function formatKickoff(iso) {
  if (!iso) return ''
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return ''
  const timeStr = dt.toLocaleString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  })
  const horizonMs = SHORT_FORMAT_HORIZON_DAYS * 24 * 60 * 60 * 1000
  const isSoon = dt.getTime() - Date.now() <= horizonMs
  if (isSoon) {
    const weekday = dt.toLocaleString('en-US', { weekday: 'short' })
    return `${weekday} ${timeStr}`
  }
  // Far out: show absolute date so "Thu" can't be misread as "this week".
  const monthDay = dt.toLocaleString('en-US', { month: 'short', day: 'numeric' })
  return `${monthDay} · ${timeStr}`
}

export default function GroupCard({ group }) {
  if (!group) return null
  const teams = group.teams || []
  const nextFixtures = (group.next_fixtures || []).slice(0, 2)
  const earliestFixture = nextFixtures[0]

  return (
    <article className="rounded-[12px] border border-white/[0.06] bg-[#111827] p-3.5">
      <header className="flex justify-between items-center mb-2.5 pb-2 border-b border-white/[0.05]">
        <div className="inline-flex items-center gap-2 text-[13px] font-extrabold">
          <span className="inline-flex items-center justify-center w-[26px] h-[26px] rounded-md bg-accent-gold/15 text-accent-gold font-extrabold text-[13px]">
            {group.label}
          </span>
          Group {group.label}
        </div>
        {group.venue ? (
          <span className="text-[10px] text-foreground-muted tracking-[0.1em] uppercase font-bold">
            {group.venue}
          </span>
        ) : null}
      </header>

      <table className="w-full text-[11px] border-collapse">
        <thead>
          <tr>
            <th className="text-[9px] text-foreground-muted font-bold tracking-[0.12em] uppercase py-1 text-left">
              Team
            </th>
            {['P', 'W', 'D', 'L', 'GD', 'Pts'].map((h) => (
              <th
                key={h}
                className="text-[9px] text-foreground-muted font-bold tracking-[0.12em] uppercase py-1 px-0.5 text-center"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {teams.map((team) => {
            const status = team.qualification_status || 'live'
            const borderColor =
              STATUS_BORDER_COLOR[status] || STATUS_BORDER_COLOR.live
            const gd = team.goal_diff ?? 0
            return (
              <tr
                key={team.team_id ?? team.name}
                className="border-t border-white/[0.04]"
              >
                <td
                  className="py-1.5 pl-2.5"
                  style={{ borderLeft: `3px solid ${borderColor}` }}
                >
                  <span className="flex items-center gap-1.5">
                    <CountryFlag code={team.country_code} size="sm" title={team.name} />
                    <span className="font-bold text-foreground text-[11px] truncate">
                      {team.name}
                    </span>
                  </span>
                </td>
                <td className="text-center py-1.5 text-tabular text-foreground-muted">{team.played}</td>
                <td className="text-center py-1.5 text-tabular text-foreground-muted">{team.wins}</td>
                <td className="text-center py-1.5 text-tabular text-foreground-muted">{team.draws}</td>
                <td className="text-center py-1.5 text-tabular text-foreground-muted">{team.losses}</td>
                <td
                  className={`text-center py-1.5 text-tabular ${
                    gd > 0 ? 'text-accent-green' : gd < 0 ? 'text-accent-red' : 'text-foreground-muted'
                  }`}
                >
                  {gd > 0 ? `+${gd}` : gd}
                </td>
                <td className="text-center py-1.5 font-extrabold text-foreground text-tabular">
                  {team.points}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {nextFixtures.length > 0 && (
        <div className="mt-2.5 pt-2 border-t border-white/[0.04] text-[10px] text-foreground-muted flex justify-between items-center gap-2">
          <span className="flex items-center gap-1.5 truncate">
            <span className="opacity-70">Next:</span>
            {nextFixtures.map((fx, i) => (
              <span key={fx.match_id ?? i} className="inline-flex items-center gap-1">
                <CountryFlag code={fx.home?.country_code} size="sm" title={fx.home?.name} />
                <span aria-hidden>vs</span>
                <CountryFlag code={fx.away?.country_code} size="sm" title={fx.away?.name} />
                {i < nextFixtures.length - 1 && <span aria-hidden className="opacity-50">·</span>}
              </span>
            ))}
          </span>
          {earliestFixture && (
            <span className="text-accent-gold font-semibold whitespace-nowrap">
              {formatKickoff(earliestFixture.kickoff)}
            </span>
          )}
        </div>
      )}
    </article>
  )
}
