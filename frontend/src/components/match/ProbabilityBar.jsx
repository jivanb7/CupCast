/**
 * ProbabilityBar — the signature component.
 * 3-segment colored bar: green (home), amber (draw), red (away).
 * Predicted outcome segment gets a subtle glow emphasis.
 */

export default function ProbabilityBar({
  probHome,
  probDraw,
  probAway,
  predictedResult,
  showLabels = true,
  size = 'md',
  teamLabels = null, // { home: string, away: string } — when provided, render team names instead of "H"/"A"
}) {
  const homePercent = Math.round((probHome ?? 0) * 100)
  const drawPercent = Math.round((probDraw ?? 0) * 100)
  const awayPercent = Math.round((probAway ?? 0) * 100)

  const barHeight = size === 'lg' ? 'h-3' : size === 'sm' ? 'h-1.5' : 'h-2'
  const homeLabel = teamLabels?.home || 'H'
  const awayLabel = teamLabels?.away || 'A'
  const drawLabel = teamLabels ? 'Draw' : 'D'

  return (
    <div>
      {/* Labels above the bar */}
      {showLabels && (
        <div className="flex justify-between mb-2 gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className={`text-xs font-medium text-tabular truncate ${
                predictedResult === 'H' ? 'text-accent-green' : 'text-foreground-muted'
              }`}
              title={homeLabel}
            >
              {homePercent}% {homeLabel}
            </span>
            {predictedResult === 'H' && (
              <span className="w-1 h-1 rounded-full bg-accent-green flex-shrink-0" />
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {predictedResult === 'D' && (
              <span className="w-1 h-1 rounded-full bg-accent-amber" />
            )}
            <span
              className={`text-xs font-medium text-tabular ${
                predictedResult === 'D' ? 'text-accent-amber' : 'text-foreground-muted'
              }`}
            >
              {drawPercent}% {drawLabel}
            </span>
          </div>
          <div className="flex items-center gap-1.5 min-w-0 justify-end">
            {predictedResult === 'A' && (
              <span className="w-1 h-1 rounded-full bg-accent-red flex-shrink-0" />
            )}
            <span
              className={`text-xs font-medium text-tabular truncate ${
                predictedResult === 'A' ? 'text-accent-red' : 'text-foreground-muted'
              }`}
              title={awayLabel}
            >
              {awayPercent}% {awayLabel}
            </span>
          </div>
        </div>
      )}

      {/* The bar */}
      <div className={`flex ${barHeight} rounded-full overflow-hidden w-full gap-px`}>
        <div
          className="rounded-l-full transition-all duration-300"
          style={{
            width: `${homePercent}%`,
            backgroundColor: predictedResult === 'H' ? '#22C55E' : 'rgba(34,197,94,0.4)',
            boxShadow: predictedResult === 'H' ? '0 0 8px rgba(34,197,94,0.3)' : 'none',
          }}
          title={`Home win: ${homePercent}%`}
          role="img"
          aria-label={`Home win probability ${homePercent}%`}
        />
        <div
          className="transition-all duration-300"
          style={{
            width: `${drawPercent}%`,
            backgroundColor: predictedResult === 'D' ? '#FBBF24' : 'rgba(251,191,36,0.4)',
            boxShadow: predictedResult === 'D' ? '0 0 8px rgba(251,191,36,0.3)' : 'none',
          }}
          title={`Draw: ${drawPercent}%`}
          role="img"
          aria-label={`Draw probability ${drawPercent}%`}
        />
        <div
          className="rounded-r-full transition-all duration-300"
          style={{
            width: `${awayPercent}%`,
            backgroundColor: predictedResult === 'A' ? '#EF4444' : 'rgba(239,68,68,0.4)',
            boxShadow: predictedResult === 'A' ? '0 0 8px rgba(239,68,68,0.3)' : 'none',
          }}
          title={`Away win: ${awayPercent}%`}
          role="img"
          aria-label={`Away win probability ${awayPercent}%`}
        />
      </div>
    </div>
  )
}
