import { useEffect, useState } from 'react'
import { getModelPerformance } from '../services/api'
import { adaptModelPerformance } from '../lib/api-adapter.js'

// Fetches `/model/performance` and reshapes for the design's headline
// numbers, last-N-days chart, and per-league strip.
// Returns `{ data, loading, error, reload }` — `data` is the adapted
// `{ accuracy, perLeague, lastWeek, overall }` bundle.
export default function useModelPerformance() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    getModelPerformance()
      .then((res) => {
        if (!alive) return
        setState({ data: adaptModelPerformance(res), loading: false, error: null })
      })
      .catch((err) => {
        if (!alive) return
        setState({ data: null, loading: false, error: err })
      })
    return () => {
      alive = false
    }
  }, [tick])

  return { ...state, reload: () => setTick((t) => t + 1) }
}
