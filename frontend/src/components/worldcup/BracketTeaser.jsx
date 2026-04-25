import CountryFlag from '../ui/CountryFlag'

/**
 * BracketTeaser — 5-card horizontal "projected path" for the model's
 * most-likely champion. Each card represents one knockout round and shows the
 * opponent the champion is projected to face plus the win-probability for
 * that single matchup.
 *
 * Layout (left → right):
 *   R32 → R16 → QF → SF → FINAL
 *
 * The FINAL card gets a gold border. Win-prob is color-coded:
 *   ≥ 70%  → green
 *   50-69% → gold
 *   < 50%  → amber
 *
 * Data source: `most_likely_champion.projected_path` from
 * GET /api/v1/world-cup/title-odds. Each entry: { stage, opponent, win_prob,
 * frequency }. Stage keys are lowercase: r32, r16, qf, sf, final.
 *
 * Empty state: if path is missing/empty (e.g. pre-tournament), we show a
 * placeholder explaining when this populates.
 */

const STAGE_ORDER = ['r32', 'r16', 'qf', 'sf', 'final']
const STAGE_LABEL = {
  r32: 'R32',
  r16: 'R16',
  qf: 'QF',
  sf: 'SF',
  final: 'FINAL',
}

function probColor(p) {
  if (p == null) return 'text-foreground-muted'
  if (p >= 0.7) return 'text-accent-green'
  if (p >= 0.5) return 'text-accent-gold'
  return 'text-accent-amber'
}

function Placeholder() {
  return (
    <section className="rounded-[14px] border border-white/[0.06] bg-[#111827] p-5 mt-[18px]">
      <div className="text-sm font-extrabold mb-1">Projected bracket path</div>
      <p className="text-xs text-foreground-muted">
        Projected path becomes available after group-stage matches complete.
      </p>
    </section>
  )
}

export default function BracketTeaser({ champion }) {
  const path = champion?.projected_path
  if (!path?.length) return <Placeholder />

  // Index by stage so we can render in canonical order even if the API
  // returns them in a different sequence.
  const byStage = Object.fromEntries(path.map((s) => [s.stage, s]))

  return (
    <section className="rounded-[14px] border border-white/[0.06] bg-[#111827] p-5 mt-[18px]">
      <header className="mb-3.5">
        <div className="text-sm font-extrabold mb-0.5">
          Projected path to the trophy ·{' '}
          <span className="text-accent-gold">{champion?.team?.name}</span>
        </div>
        <div className="text-xs text-foreground-muted">
          Opponents the model expects {champion?.team?.name} to face at each
          knockout round, with the per-matchup win probability.
        </div>
      </header>

      <ol
        className="grid gap-1.5 list-none p-0 m-0"
        style={{ gridTemplateColumns: 'repeat(5, minmax(0, 1fr))' }}
      >
        {STAGE_ORDER.map((stageKey) => {
          const slot = byStage[stageKey]
          const isFinal = stageKey === 'final'
          const opp = slot?.opponent
          const pct = slot?.win_prob != null ? Math.round(slot.win_prob * 100) : null

          return (
            <li
              key={stageKey}
              className={`rounded-md px-2 py-2 text-center border ${
                isFinal
                  ? 'border-accent-gold/45 bg-accent-gold/[0.10]'
                  : 'border-white/[0.06] bg-[#0b1220]'
              }`}
            >
              <div
                className={`text-[9px] tracking-[0.15em] uppercase font-bold mb-1 ${
                  isFinal ? 'text-accent-gold' : 'text-foreground-muted'
                }`}
              >
                {STAGE_LABEL[stageKey]}
              </div>

              {opp ? (
                <>
                  <div className="flex items-center justify-center gap-1 text-[11px] font-bold text-foreground truncate">
                    <CountryFlag code={opp.country_code} size="sm" title={opp.name} />
                    <span className="truncate">{opp.name}</span>
                  </div>
                  <div
                    className={`text-[10px] font-extrabold mt-1 text-tabular ${probColor(slot.win_prob)}`}
                  >
                    {pct != null ? `${pct}%` : '—'}
                  </div>
                </>
              ) : (
                <>
                  <div className="text-[11px] font-bold text-foreground-muted italic">TBD</div>
                  <div className="text-[10px] text-foreground-muted mt-1">—</div>
                </>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
