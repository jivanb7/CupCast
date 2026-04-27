import { useEffect, useRef, useState } from 'react'

export default function useInView({ threshold = 0.15, once = true } = {}) {
  const ref = useRef(null)
  const [vis, setVis] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setVis(true)
          if (once) io.disconnect()
        } else if (!once) {
          setVis(false)
        }
      },
      { threshold }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [threshold, once])
  return [ref, vis]
}
