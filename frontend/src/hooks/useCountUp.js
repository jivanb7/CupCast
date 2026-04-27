import { useEffect, useState } from 'react'

export default function useCountUp(target, { duration = 800, delay = 0, overshoot = 1.06 } = {}) {
  const [v, setV] = useState(0)
  useEffect(() => {
    let raf
    let t0 = null
    const step = (t) => {
      if (!t0) t0 = t
      const elapsed = t - t0 - delay
      if (elapsed < 0) { raf = requestAnimationFrame(step); return }
      const k = Math.min(1, elapsed / duration)
      const eased = k < 0.85
        ? 1 - Math.pow(1 - k / 0.85, 3)
        : 1 - (1 - overshoot) * (1 - (k - 0.85) / 0.15)
      setV(target * eased)
      if (k < 1) raf = requestAnimationFrame(step)
      else setV(target)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, duration, delay, overshoot])
  return v
}
