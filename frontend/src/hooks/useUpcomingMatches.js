import { useEffect, useState } from 'react'
import { getUpcomingMatches } from '../services/api'
import { adaptMatches } from '../lib/api-adapter.js'

// Fetches `/matches/upcoming` and adapts each row into the CC Match shape
// (decorate'd, so call/edge/value fields are computed). Returns a stable
// `{ matches, loading, error, reload }` triple. Pass a leagueCode (e.g. 'epl')
// to filter server-side, or null/undefined for the full slate.
export default function useUpcomingMatches({ leagueCode = null, daysAhead = 7 } = {}) {
  const [state, setState] = useState({ matches: [], loading: true, error: null })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    getUpcomingMatches(leagueCode || null, daysAhead)
      .then((res) => {
        if (!alive) return
        setState({ matches: adaptMatches(res?.matches || []), loading: false, error: null })
      })
      .catch((err) => {
        if (!alive) return
        setState({ matches: [], loading: false, error: err })
      })
    return () => {
      alive = false
    }
  }, [leagueCode, daysAhead, tick])

  return { ...state, reload: () => setTick((t) => t + 1) }
}
