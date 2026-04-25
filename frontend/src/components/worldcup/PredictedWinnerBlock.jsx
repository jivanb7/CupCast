import CountryFlag from '../ui/CountryFlag'

/**
 * PredictedWinnerBlock — gold-trophy showcase of the model's most likely
 * tournament winner. Stitches a rationale paragraph from facts[] + key_risk
 * (frontend assembly per task spec) and shows the projected knockout path.
 *
 * Props:
 *   champion: response.most_likely_champion from /world-cup/title-odds
 *   topContenderStats: optional title_contenders[0..N] — used to look up
 *                      survival pcts for the bottom-row stats
 */

const STAGE_LABELS = {
  r32: 'R32',
  r16: 'R16',
  qf: 'QF',
  sf: 'SF',
  final: 'FINAL',
}

function pctToOdds(pct) {
  if (!pct || pct <= 0) return '—'
  const decimal = 100 / pct
  return decimal >= 10 ? decimal.toFixed(1) : decimal.toFixed(2)
}

function buildRationaleParagraph(champion, runnerUp) {
  if (!champion) return ''
  const facts = champion.rationale?.facts || []
  const keyRisk = champion.rationale?.key_risk
  const teamName = champion.team?.name || 'The leader'
  const pct = champion.win_tournament_pct?.toFixed(1) ?? '?'

  // Opener — explicitly contrasts the champion against the runner-up so the
  // 21.9% vs 19.3% near-tie is acknowledged, not glossed over.
  let opener
  if (runnerUp?.name && typeof runnerUp.win_tournament_pct === 'number') {
    const rPct = runnerUp.win_tournament_pct.toFixed(1)
    opener = `${teamName} leads the field at ${pct}% — narrowly ahead of ${runnerUp.name} (${rPct}%), but with the strongest overall projected run.`
  } else {
    opener = `${teamName} leads the field at ${pct}% with the strongest overall projected run.`
  }

  // Render up to three facts as their own short clauses.
  const factSentences = facts
    .slice(0, 3)
    .map((f) => `${f.label}: ${f.value}.`)
    .join(' ')
  const factPart = factSentences ? ` ${factSentences}` : ''

  let riskSentence = ''
  if (keyRisk?.opponent && keyRisk?.stage) {
    const stage = (keyRisk.stage || '').toUpperCase()
    const opp = keyRisk.opponent.name
    const expl = keyRisk.explanation || ''
    // New explanation strings already mention the opponent + win-prob owner
    // ("we're 54% favored against Argentina"), so we omit them from the
    // matchup prefix when the explanation carries that detail.
    const explanationCarriesOpponent = expl.toLowerCase().includes(opp.toLowerCase())
    const matchupPrefix = explanationCarriesOpponent
      ? `${stage} matchup`
      : `${stage} matchup vs ${opp}`
    riskSentence = ` Key risk: ${matchupPrefix} — ${expl}.`
  }

  return `${opener}${factPart}${riskSentence}`
}

export default function PredictedWinnerBlock({ champion, topContenderStats }) {
  if (!champion) return null

  // Runner-up = first contender that isn't the champion (handles the case
  // where contenders is sorted by rank and includes the champion at idx 0).
  const runnerUp = (topContenderStats || []).find(
    (c) => c.team_id !== champion.team_id
  )
  const rationale = buildRationaleParagraph(champion, runnerUp)
  const winPct = champion.win_tournament_pct ?? 0
  const odds = pctToOdds(winPct)

  // Survival stats from contenders list (matches by team_id).
  const teamId = champion.team_id
  const stats = (topContenderStats || []).find((c) => c.team_id === teamId) || {}
  const reachFinal = stats.reach_final_pct ?? null
  const reachSemis = stats.reach_semis_pct ?? null
  const reachQf = stats.reach_qf_pct ?? null

  return (
    <section
      className="relative overflow-hidden rounded-[16px] border border-accent-gold/40 px-6 py-5 mb-[18px]"
      style={{
        background: `
          radial-gradient(circle at 15% 20%, rgba(245,158,11,0.18), transparent 55%),
          linear-gradient(135deg, rgba(245,158,11,0.14) 0%, rgba(11,18,32,0.5) 65%)
        `,
      }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute select-none"
        style={{
          top: -20,
          right: 18,
          fontSize: 110,
          opacity: 0.06,
          filter: 'grayscale(1) brightness(1.8)',
        }}
      >
        🏆
      </span>

      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 mb-3.5 rounded-full text-[10px] font-extrabold tracking-[0.2em] uppercase text-accent-gold border border-accent-gold/45 bg-accent-gold/[0.18]">
        <span aria-hidden>◆</span> Our Pick · World Cup Winner 2026
      </div>

      <div className="grid lg:grid-cols-[auto_1fr_220px] gap-6 lg:gap-7 items-center">
        {/* Crest column */}
        <div className="flex flex-col items-center gap-2.5">
          <div
            className="rounded-[10px] overflow-hidden border-2 border-accent-gold/50"
            style={{ width: 140, height: 94, boxShadow: '0 12px 28px rgba(0,0,0,0.55)' }}
          >
            <span
              className={`fi fi-${(champion.team?.country_code || '').toLowerCase()} fis`}
              style={{ display: 'block', width: '100%', height: '100%' }}
              aria-label={champion.team?.name}
            />
          </div>
          <div
            className="text-[26px] font-black tracking-[-0.02em]"
            style={{
              background: 'linear-gradient(135deg, #fff, #F59E0B)',
              WebkitBackgroundClip: 'text',
              backgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            {champion.team?.name}
          </div>
        </div>

        {/* Middle column: rationale + projected path */}
        <div>
          <div className="text-[10px] tracking-[0.18em] uppercase font-bold text-foreground-muted mb-1">
            Why {champion.team?.name}
          </div>
          <p className="text-[15px] font-medium text-[#c7cdd8] leading-[1.55] mb-3.5">
            {rationale}
          </p>

          <div className="text-[10px] tracking-[0.18em] uppercase font-bold text-foreground-muted mb-1.5">
            Projected path to the trophy
          </div>
          <ol className="grid grid-cols-5 gap-1.5 list-none p-0 m-0">
            {(champion.projected_path || []).map((slot) => {
              const isFinal = slot.stage === 'final'
              const probPct = Math.round((slot.win_prob ?? 0) * 100)
              const isLow = probPct < 60
              return (
                <li
                  key={slot.stage}
                  className={`rounded-[8px] px-1.5 py-1.5 text-center ${
                    isFinal
                      ? 'border border-accent-gold/45 bg-accent-gold/10'
                      : 'border border-white/[0.06] bg-black/30'
                  }`}
                >
                  <div
                    className={`text-[8px] tracking-[0.15em] uppercase font-bold mb-1 ${
                      isFinal ? 'text-accent-gold' : 'text-foreground-muted'
                    }`}
                  >
                    {STAGE_LABELS[slot.stage] || slot.stage}
                  </div>
                  <div className="flex items-center justify-center gap-1 text-[11px] font-bold text-foreground">
                    <CountryFlag
                      code={slot.opponent?.country_code}
                      size="sm"
                      title={slot.opponent?.name}
                    />
                    <span className="truncate">{slot.opponent?.name}</span>
                  </div>
                  <div
                    className={`text-[10px] font-extrabold mt-1 text-tabular ${
                      isLow ? 'text-accent-amber' : 'text-accent-green'
                    }`}
                  >
                    {probPct}%
                  </div>
                </li>
              )
            })}
          </ol>
        </div>

        {/* Right column: big % */}
        <div className="rounded-[12px] border border-accent-gold/30 bg-black/35 px-4 py-3.5 text-center">
          <div className="text-[50px] font-black text-accent-gold tracking-[-0.03em] leading-[0.95] text-tabular">
            {winPct.toFixed(1)}%
          </div>
          <div className="text-[10px] tracking-[0.18em] uppercase font-bold text-foreground-muted mt-1.5">
            Win-Tournament
          </div>
          <div className="text-[11px] text-foreground-muted mt-2 pt-2 border-t border-white/[0.06] text-tabular">
            Implied odds <b className="text-foreground">{odds}</b>
          </div>
        </div>
      </div>

      {/* Survival stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mt-4 pt-3.5 border-t border-accent-gold/15">
        <SurvivalStat label="Win WC" value={`${winPct.toFixed(1)}%`} gold />
        <SurvivalStat
          label="Reach final"
          value={reachFinal != null ? `${reachFinal.toFixed(1)}%` : '—'}
        />
        <SurvivalStat
          label="Reach semis"
          value={reachSemis != null ? `${reachSemis.toFixed(1)}%` : '—'}
        />
        <SurvivalStat
          label="Reach quarters"
          value={reachQf != null ? `${reachQf.toFixed(1)}%` : '—'}
        />
      </div>
    </section>
  )
}

function SurvivalStat({ label, value, gold = false }) {
  return (
    <div className="text-center">
      <div
        className={`text-[18px] font-extrabold tracking-[-0.02em] text-tabular ${
          gold ? 'text-accent-gold' : 'text-foreground'
        }`}
      >
        {value}
      </div>
      <div className="text-[10px] tracking-[0.14em] uppercase font-bold text-foreground-muted mt-0.5">
        {label}
      </div>
    </div>
  )
}
