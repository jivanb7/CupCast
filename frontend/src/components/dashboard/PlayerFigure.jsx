import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'

/**
 * PlayerFigure — single player image with scroll + mouse parallax,
 * theme-aware tinting, reveal-on-mount. Equal heights across the rail;
 * depth differences come from opacity + parallax + z-stack only.
 */
export default function PlayerFigure({
  src, alt, side = 'left', depth = 0.5,
  yOffset = 0, xOffset = 0, heightVh = 42, widthPx, tone = 'neutral', zIndex = 1,
}) {
  const [scrollY, setScrollY] = useState(0)

  useEffect(() => {
    let raf = 0
    let target = 0, current = 0
    const onScroll = () => { target = window.scrollY }
    const tick = () => {
      current += (target - current) * 0.1
      setScrollY(current)
      raf = requestAnimationFrame(tick)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    raf = requestAnimationFrame(tick)
    return () => {
      window.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(raf)
    }
  }, [])

  // Subtle parallax — depth 1 (front) barely moves, depth 0 (back) drifts a bit.
  // User wants players to feel stationary, so factor stays small.
  const parallaxFactor = 0.02 + (1 - depth) * 0.05
  const ty = -scrollY * parallaxFactor
  const opacity = 0.82 + depth * 0.16
  const mxStrength = (side === 'left' ? -1 : 1) * (3 + depth * 3)
  const myStrength = -1 - depth

  return (
    <div
      className={`cc-player cc-player-${tone}`}
      style={{
        top: `${yOffset}vh`,
        [side]: `${xOffset}%`,
        height: `${heightVh}vh`,
        ...(widthPx ? { width: `${widthPx}px` } : null),
        zIndex,
        '--depth': depth,
        '--mx-strength': `${mxStrength}px`,
        '--my-strength': `${myStrength}px`,
      }}
    >
      <motion.div
        className="cc-player-reveal"
        initial={{ opacity: 0, x: side === 'left' ? -30 : 30 }}
        animate={{ opacity, x: 0 }}
        transition={{ duration: 0.85, delay: 0.12 + depth * 0.15, ease: [0.22, 1, 0.36, 1] }}
      >
        <div
          className="cc-player-scroll"
          style={{ transform: `translate3d(0, ${ty.toFixed(1)}px, 0)` }}
        >
          <div className="cc-player-inner">
            <img src={src} alt={alt} draggable="false" loading="lazy" />
          </div>
        </div>
      </motion.div>
    </div>
  )
}
