import { useEffect } from 'react'
import Lenis from '@studio-freight/lenis'

let lenisInstance = null
let mountCount = 0

export function getLenis() {
  return lenisInstance
}

export default function useLenisScroll() {
  useEffect(() => {
    mountCount += 1
    if (!lenisInstance) {
      lenisInstance = new Lenis({
        duration: 1.05,
        easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        smoothWheel: true,
        smoothTouch: false,
      })
      const raf = (time) => {
        lenisInstance?.raf(time)
        requestAnimationFrame(raf)
      }
      requestAnimationFrame(raf)
    }
    return () => {
      mountCount -= 1
      if (mountCount <= 0 && lenisInstance) {
        lenisInstance.destroy()
        lenisInstance = null
        mountCount = 0
      }
    }
  }, [])
}
