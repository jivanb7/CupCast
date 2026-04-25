/**
 * StageProgressStrip — six-cell breadcrumb of tournament stages.
 *
 * Highlights the current stage in gold and marks completed stages with
 * a green checkmark. Pre-tournament collapses to "Group Stage" highlighted
 * as next-up.
 *
 * Props:
 *   currentStage:    one of 'pre' | 'group' | 'r32' | 'r16' | 'qf' | 'sf' | 'final' | 'done'
 *   currentMatchday: integer (1..3 for group, otherwise null)
 */

const STAGES = [
  { key: 'group', label: 'Group Stage' },
  { key: 'r32', label: 'Round of 32' },
  { key: 'r16', label: 'Round of 16' },
  { key: 'qf', label: 'Quarter-Finals' },
  { key: 'sf', label: 'Semi-Finals' },
  { key: 'final', label: 'Final' },
]

const SUBLABELS = {
  group: 'Jun 11 → Jun 27',
  r32: 'Jun 29 → Jul 3',
  r16: 'Jul 4 → Jul 7',
  qf: 'Jul 9 → Jul 11',
  sf: 'Jul 14 → Jul 15',
  final: 'Jul 19 · MetLife, NJ',
}

const ORDER = ['group', 'r32', 'r16', 'qf', 'sf', 'final']

export default function StageProgressStrip({ currentStage, currentMatchday }) {
  const normalized = currentStage === 'pre' ? null : currentStage
  const currentIdx = normalized ? ORDER.indexOf(normalized) : -1

  return (
    <div
      className="flex gap-1 rounded-[14px] border border-white/[0.06] bg-[#111827] p-2 mb-3.5"
      role="list"
      aria-label="Tournament stage progress"
    >
      {STAGES.map((stage) => {
        const idx = ORDER.indexOf(stage.key)
        const isActive = idx === currentIdx
        // Pre-tournament: mark group stage as next-up
        const isPreNextUp = currentIdx === -1 && stage.key === 'group'
        const isDone = currentIdx > idx
        const showActive = isActive || isPreNextUp

        let classes = 'flex-1 px-2.5 py-2.5 text-center rounded-[10px] text-xs font-semibold transition-colors'
        if (showActive) {
          classes += ' bg-accent-gold/10 text-accent-gold border border-accent-gold/35'
        } else if (isDone) {
          classes += ' text-accent-green'
        } else {
          classes += ' text-foreground-muted'
        }

        let sub = SUBLABELS[stage.key]
        if (showActive && stage.key === 'group' && currentMatchday) {
          sub = `Matchday ${currentMatchday} of 3`
        } else if (isPreNextUp) {
          sub = 'Up next'
        }

        return (
          <div key={stage.key} className={classes} role="listitem">
            <div className="flex items-center justify-center gap-1.5">
              <span>{stage.label}</span>
              {isDone && <span aria-label="completed" className="text-[10px]">✓</span>}
            </div>
            {sub && (
              <div className="text-[10px] mt-0.5 opacity-75 font-medium">{sub}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}
