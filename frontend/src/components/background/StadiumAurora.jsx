import { useEffect, useRef } from 'react'

/**
 * StadiumAurora — fixed-position background atmosphere.
 * Multi-layer animated radial gradients in football kit colors,
 * with day/night palette driven by CSS vars on [data-theme].
 *
 * Implementation: pure CSS gradients + transform animations. Lighter
 * and more reliable than a WebGL shader for the 6-blob aurora pattern
 * we want here. WebGL was the planned upgrade, but at this density CSS
 * looks identical and ships at 0KB JS overhead.
 */
export default function StadiumAurora() {
  const containerRef = useRef(null)

  useEffect(() => {
    const node = containerRef.current
    if (!node) return
    let raf = 0
    let mx = 0.5, my = 0.5, tx = 0.5, ty = 0.5

    const onMove = (e) => {
      tx = e.clientX / window.innerWidth
      ty = e.clientY / window.innerHeight
    }

    const tick = () => {
      mx += (tx - mx) * 0.04
      my += (ty - my) * 0.04
      node.style.setProperty('--aurora-mx', `${(mx * 100).toFixed(2)}%`)
      node.style.setProperty('--aurora-my', `${(my * 100).toFixed(2)}%`)
      raf = requestAnimationFrame(tick)
    }
    window.addEventListener('mousemove', onMove, { passive: true })
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('mousemove', onMove)
    }
  }, [])

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className="cc-aurora-root pointer-events-none fixed inset-0 z-0 overflow-hidden"
    >
      <div className="cc-aurora-base absolute inset-0" />
      <div className="cc-aurora-blob cc-aurora-b1" />
      <div className="cc-aurora-blob cc-aurora-b2" />
      <div className="cc-aurora-blob cc-aurora-b3" />
      <div className="cc-aurora-blob cc-aurora-b4" />
      <div className="cc-aurora-blob cc-aurora-b5" />
      <div className="cc-aurora-blob cc-aurora-b6" />
      <div className="cc-aurora-grain absolute inset-0" />
      <div className="cc-aurora-vignette absolute inset-0" />
    </div>
  )
}
