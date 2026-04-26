import PlayerFigure from './PlayerFigure'

/**
 * PlayerRail — overlapping cluster of player figures on one viewport edge.
 * Each player's position (xPct, yVh, z, h) is hand-tuned in Dashboard.jsx
 * so faces stay visible while shoulders overlap — soccer-photoshoot style.
 *
 * Hidden below 1280px (xl). Peripheral imagery is desktop-luxury.
 */
export default function PlayerRail({ side, players }) {
  return (
    <div
      className={`cc-rail cc-rail-${side} pointer-events-none fixed top-0 z-[5] hidden xl:block`}
      aria-hidden="true"
    >
      {players.map((p, i) => {
        const depth = (p.z - 1) / Math.max(1, players.length - 1) // 0 back → 1 front
        return (
          <PlayerFigure
            key={p.alt}
            src={p.src}
            alt={p.alt}
            side={side}
            depth={depth}
            yOffset={p.yVh}
            xOffset={p.xPct}
            heightVh={p.h}
            widthPx={p.w}
            tone={p.tone}
            zIndex={p.z}
          />
        )
      })}
    </div>
  )
}
