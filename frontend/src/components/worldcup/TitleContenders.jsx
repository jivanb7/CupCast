import CountryFlag from '../ui/CountryFlag'

/**
 * TitleContenders — top-8 grid of championship contenders.
 *
 * Top 4 cards get gold-bordered emphasis. Each card shows flag, team name,
 * win-tournament %, derived odds, and a horizontal probability bar
 * normalized against the leader.
 *
 * Props:
 *   contenders:        array of { team_id, name, country_code, win_tournament_pct, ... }
 *   totalContenders:   total length of the unsliced contender list (for footer)
 */

function pctToOdds(pct) {
  if (!pct || pct <= 0) return '—'
  const decimal = 100 / pct
  return decimal >= 10 ? decimal.toFixed(1) : decimal.toFixed(2)
}

export default function TitleContenders({ contenders = [], totalContenders }) {
  const top8 = contenders.slice(0, 8)
  const total = totalContenders ?? contenders.length

  if (!top8.length) return null

  const leaderPct = top8[0]?.win_tournament_pct ?? 1
  const top8Sum = top8.reduce((sum, t) => sum + (t.win_tournament_pct ?? 0), 0)
  const remaining = Math.max(0, 100 - top8Sum)
  const otherCount = Math.max(0, total - 8)

  return (
    <section className="rounded-[14px] border border-white/[0.06] bg-[#111827] px-5 py-[18px] mb-[18px]">
      <header className="flex justify-between items-baseline mb-3">
        <h2 className="text-[20px] font-extrabold tracking-[-0.01em]">Title contenders</h2>
        <span
          className="text-[11px] text-foreground-muted font-medium cursor-help"
          title="CupCast simulates the rest of the tournament many times using current team ratings to estimate each team's title chances."
          aria-label="How title contenders are calculated"
        >
          ⓘ How this is calculated
        </span>
      </header>

      <ol className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 list-none p-0 m-0">
        {top8.map((team, i) => {
          const rank = i + 1
          const isTop = rank <= 4
          const pct = team.win_tournament_pct ?? 0
          const fillWidth = leaderPct > 0 ? Math.max(4, (pct / leaderPct) * 100) : 4
          const odds = pctToOdds(pct)

          return (
            <li
              key={team.team_id ?? team.name}
              className={`relative rounded-[10px] p-3 flex flex-col gap-2 transition-colors ${
                isTop
                  ? 'border border-accent-gold/40 bg-gradient-to-b from-accent-gold/[0.08] to-[#0b1220]'
                  : 'border border-white/[0.06] bg-[#0b1220] hover:border-accent-gold/30'
              }`}
            >
              <span className="absolute top-2 right-2.5 text-[10px] font-extrabold tracking-[0.1em] text-foreground-muted">
                #{rank}
              </span>
              <div className="flex items-center gap-2.5">
                <CountryFlag code={team.country_code} size="lg" title={team.name} />
                <span className="text-sm font-extrabold tracking-[-0.01em] truncate">
                  {team.name}
                </span>
              </div>
              <div
                className="h-1.5 rounded-full bg-white/[0.08] overflow-hidden"
                role="img"
                aria-label={`${team.name}: ${pct.toFixed(1)} percent chance to win the tournament`}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${fillWidth}%`,
                    background: 'linear-gradient(90deg, #F59E0B, #FBBF24)',
                  }}
                />
              </div>
              <div className="flex justify-between items-baseline text-[11px]">
                <span className="text-[17px] font-extrabold text-accent-gold tracking-[-0.02em] text-tabular">
                  {pct.toFixed(1)}%
                </span>
                <span className="text-foreground-muted text-tabular">odds {odds}</span>
              </div>
            </li>
          )
        })}
      </ol>

      <div className="mt-3 pt-2.5 border-t border-white/[0.06] text-[11px] text-foreground-muted text-center">
        Remaining {remaining.toFixed(1)}% distributed across {otherCount} other contender{otherCount === 1 ? '' : 's'}
      </div>
    </section>
  )
}
