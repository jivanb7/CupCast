import { useEffect, useState } from 'react'
import { getResults } from '../services/api'
import { adaptMatches } from '../lib/api-adapter.js'

// Fetches `/matches/results` (completed matches) and adapts each row.
// Returns `{ matches, loading, error, accuracy, reload }`. The accuracy
// figure is the prediction-hit-rate computed server-side over the window.
export default function useRecentMatches({ leagueCode = null, daysBack = 7 } = {}) {
  const [state, setState] = useState({ matches: [], accuracy: null, loading: true, error: null })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    getResults(leagueCode || null, daysBack)
      .then((res) => {
        if (!alive) return
        setState({
          matches: adaptMatches(res?.matches || []),
          accuracy: res?.prediction_accuracy ?? null,
          loading: false,
          error: null,
        })
      })
      .catch((err) => {
        if (!alive) return
        setState({ matches: [], accuracy: null, loading: false, error: err })
      })
    return () => {
      alive = false
    }
  }, [leagueCode, daysBack, tick])

  return { ...state, reload: () => setTick((t) => t + 1) }
}
