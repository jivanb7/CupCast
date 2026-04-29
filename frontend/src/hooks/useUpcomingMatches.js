import { useEffect, useRef, useState } from 'react'
import { getUpcomingMatches } from '../services/api'
import { adaptMatches } from '../lib/api-adapter.js'

// Polling cadences for the slate. When ANY match in the returned list is
// live we want a tight loop so the score / minute updates without a manual
// refresh. With nothing live, fall back to a slow tick so the next-up cards
// still pick up status flips (SCHEDULED → LIVE) within a minute or two.
const LIVE_POLL_MS = 30_000   // 30 s when at least one match is live.
const IDLE_POLL_MS = 5 * 60_000 // 5 min when the slate is all scheduled / FT.

// Fetches `/matches/upcoming` and adapts each row into the CC Match shape
// (decorate'd, so call/edge/value fields are computed). Returns a stable
// `{ matches, loading, error, reload }` triple. Pass a leagueCode (e.g. 'epl')
// to filter server-side, or null/undefined for the full slate.
//
// Auto-refreshes on its own. Tabs that go hidden pause the loop and
// refetch immediately when the tab becomes visible again.
export default function useUpcomingMatches({ leagueCode = null, daysAhead = 7 } = {}) {
  const [state, setState] = useState({ matches: [], loading: true, error: null })
  const [tick, setTick] = useState(0)
  const hasLiveRef = useRef(false)

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    getUpcomingMatches(leagueCode || null, daysAhead)
      .then((res) => {
        if (!alive) return
        const matches = adaptMatches(res?.matches || [])
        hasLiveRef.current = matches.some((m) => m.status === 'LIVE')
        setState({ matches, loading: false, error: null })
      })
      .catch((err) => {
        if (!alive) return
        setState({ matches: [], loading: false, error: err })
      })
    return () => {
      alive = false
    }
  }, [leagueCode, daysAhead, tick])

  // Auto-refresh loop. Re-arms after every fetch so a SCHEDULED → LIVE
  // flip in the result set bumps us to the fast cadence next interval.
  useEffect(() => {
    const interval = hasLiveRef.current ? LIVE_POLL_MS : IDLE_POLL_MS

    const bumpTick = () => setTick((t) => t + 1)

    let timerId
    const start = () => {
      clearTimeout(timerId)
      timerId = setTimeout(bumpTick, interval)
    }
    const stop = () => clearTimeout(timerId)

    const onVisibility = () => {
      if (document.hidden) {
        stop()
      } else {
        bumpTick()
      }
    }

    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [tick, state.matches])

  return { ...state, reload: () => setTick((t) => t + 1) }
}
