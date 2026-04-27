import { useEffect, useState } from 'react'
import { getMatch } from '../services/api'
import { adaptMatch } from '../lib/api-adapter.js'

// Fetches `/matches/{id}` (full detail with form + h2h) and adapts the
// result. Form arrays + h2h list are passed through untouched so pages
// can use `match.home_form.last_5_results`, `match.h2h_last_5`, etc.
//
// Returns `{ match, raw, loading, error, reload }`. `match` is the
// CC-shaped + decorated object the design pages already consume.
// `raw` is the original API response (so callers can read shots/corners
// without new field plumbing on every backend addition).
export default function useMatchDetail(matchId) {
  const [state, setState] = useState({ match: null, raw: null, loading: true, error: null })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!matchId) {
      setState({ match: null, raw: null, loading: false, error: null })
      return undefined
    }
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    getMatch(matchId)
      .then((res) => {
        if (!alive) return
        const adapted = adaptMatch(res)
        // Forward form + h2h onto the adapted object so the reasoning
        // library and the form/h2h sections can read them off `match`.
        if (adapted) {
          adapted.home_form = res.home_form || null
          adapted.away_form = res.away_form || null
          adapted.h2h_last_5 = res.h2h_last_5 || []
          adapted.home_shots = res.home_shots
          adapted.away_shots = res.away_shots
          adapted.home_shots_on_target = res.home_shots_on_target
          adapted.away_shots_on_target = res.away_shots_on_target
          adapted.home_corners = res.home_corners
          adapted.away_corners = res.away_corners
          adapted.explanationText = res.prediction?.explanation_text || null
        }
        setState({ match: adapted, raw: res, loading: false, error: null })
      })
      .catch((err) => {
        if (!alive) return
        setState({ match: null, raw: null, loading: false, error: err })
      })
    return () => {
      alive = false
    }
  }, [matchId, tick])

  return { ...state, reload: () => setTick((t) => t + 1) }
}
