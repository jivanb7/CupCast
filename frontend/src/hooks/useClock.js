import { useEffect, useState } from 'react'

export default function useClock(start = 0) {
  const [t, setT] = useState(start)
  useEffect(() => {
    const id = setInterval(() => setT((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [])
  return t
}
