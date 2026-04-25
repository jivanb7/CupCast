import { Link } from 'react-router-dom'
import CountryFlag from '../ui/CountryFlag'

/**
 * UpcomingWCFixtures — table of WC fixtures with model picks + value chips.
 *
 * Props:
 *   fixtures: list of MatchSummary (each with home_team_country_code,
 *             away_team_country_code, group_label, prediction)
 *   title:    string (e.g. "Today's WC fixtures" or "Upcoming WC fixtures")
 */

function formatTimeAndDay(match) {
  const time = match.kickoff_time && match.kickoff_time !== 'nan' && match.kickoff_time !== 'NaN'
    ? match.kickoff_time
    : '12:00'
  const dt = new Date(`${match.match_date}T${time}:00Z`)
  if (Number.isNaN(dt.getTime())) return { time: time, day: match.match_date }

  const today = new Date()
  const isToday = dt.toDateString() === today.toDateString()
  const tomorrow = new Date(today)
  tomorrow.setDate(today.getDate() + 1)
  const isTomorrow = dt.toDateString() === tomorrow.toDateString()

  let dayLabel
  if (isToday) dayLabel = 'Today'
  else if (isTomorrow) dayLabel = 'Tomorrow'
  else dayLabel = dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })

  const timeLabel = dt.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  })

  return { time: timeLabel, day: dayLabel }
}

function pickFor(match) {
  const pred = match.prediction
  if (!pred) return null
  const home = pred.prob_home_win ?? 0
  const draw = pred.prob_draw ?? 0
  const away = pred.prob_away_win ?? 0
  const max = Math.max(home, draw, away)
  let teamLabel
  if (max === home) teamLabel = match.home_team_short_name || match.home_team_name
  else if (max === away) teamLabel = match.away_team_short_name || match.away_team_name
  else teamLabel = 'Draw'
  return {
    team: teamLabel,
    pct: Math.round(max * 100),
    isValue: pred.is_value_pick,
  }
}

export default function UpcomingWCFixtures({ fixtures = [], title = 'Upcoming WC fixtures' }) {
  if (!fixtures.length) {
    return (
      <section className="rounded-[14px] border border-white/[0.06] bg-[#111827] px-5 py-5 mt-[18px]">
        <h3 className="text-[15px] font-extrabold mb-1">{title}</h3>
        <p className="text-foreground-muted text-sm py-3">No upcoming World Cup fixtures at this moment.</p>
      </section>
    )
  }

  return (
    <section className="rounded-[14px] border border-white/[0.06] bg-[#111827] px-5 py-[18px] mt-[18px]">
      <header className="flex justify-between items-baseline mb-1">
        <h3 className="text-[15px] font-extrabold">{title}</h3>
        <span className="text-[11px] text-foreground-muted">
          {fixtures.length} match{fixtures.length === 1 ? '' : 'es'} · model picks + value flags
        </span>
      </header>

      <ul className="list-none p-0 m-0">
        {fixtures.map((m) => {
          const { time, day } = formatTimeAndDay(m)
          const pick = pickFor(m)
          return (
            <li
              key={m.id}
              className="grid items-center gap-2 py-2.5 border-b border-white/[0.04] last:border-b-0 text-xs"
              style={{
                gridTemplateColumns: 'minmax(70px, 88px) minmax(0, 1fr) 56px minmax(0, 1fr) 60px minmax(120px, 160px)',
              }}
            >
              <Link
                to={`/match/${m.id}`}
                className="text-accent-gold font-bold text-[11px] hover:underline"
              >
                {time}
                <span className="block text-foreground-muted text-[10px] tracking-[0.08em] uppercase font-medium mt-0.5">
                  {day}
                </span>
              </Link>
              <Link to={`/match/${m.id}`} className="flex items-center gap-2 font-bold truncate">
                <CountryFlag code={m.home_team_country_code} size="md" title={m.home_team_name} />
                <span className="truncate">{m.home_team_short_name || m.home_team_name}</span>
              </Link>
              <span className="text-[11px] text-foreground-muted text-center font-bold tracking-[0.15em]">
                VS
              </span>
              <Link to={`/match/${m.id}`} className="flex items-center gap-2 font-bold justify-end truncate">
                <span className="truncate">{m.away_team_short_name || m.away_team_name}</span>
                <CountryFlag code={m.away_team_country_code} size="md" title={m.away_team_name} />
              </Link>
              <span className="text-[10px] text-foreground-muted text-center tracking-[0.1em] uppercase font-bold">
                {m.group_label ? `Grp ${m.group_label}` : (m.stage || '').toUpperCase() || ''}
              </span>
              <div className="flex gap-1.5 items-center justify-end text-[11px]">
                {pick ? (
                  <>
                    <span className="font-bold text-foreground truncate">{pick.team}</span>
                    <span className="font-extrabold text-accent-gold text-tabular">{pick.pct}%</span>
                    {pick.isValue && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold tracking-[0.1em] uppercase text-accent-gold border border-accent-gold/35 bg-accent-gold/15">
                        ◆ Val
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-foreground-muted text-[10px]">No pick</span>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
