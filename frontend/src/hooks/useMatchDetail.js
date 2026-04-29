import { useEffect, useRef, useState } from 'react'
import { getMatch } from '../services/api'
import { adaptMatch } from '../lib/api-adapter.js'

// Polling cadences. Live matches need to feel real-time; scheduled rows can
// drift on a longer interval since nothing changes until kickoff. Keeping
// these as constants so the values are easy to find when tuning later.
const LIVE_POLL_MS = 25_000   // ~25 s — close to the backend's 60s live-sync
                              // cron without hammering Cloud Run.
const IDLE_POLL_MS = 5 * 60_000 // 5 min for scheduled / FT detail pages.

// Fetches `/matches/{id}` (full detail with form + h2h) and adapts the
// result. Form arrays + h2h list are passed through untouched so pages
// can use `match.home_form.last_5_results`, `match.h2h_last_5`, etc.
//
// Auto-refreshes on its own so the score / minute / status update
// without a user-triggered reload. Cadence bumps to LIVE_POLL_MS when the
// match status is 'LIVE', otherwise IDLE_POLL_MS. Polling pauses when the
// tab is hidden and refetches immediately when it becomes visible again.
//
// Returns `{ match, raw, loading, error, reload }`. `match` is the
// CC-shaped + decorated object the design pages already consume.
// `raw` is the original API response (so callers can read shots/corners
// without new field plumbing on every backend addition).
export default function useMatchDetail(matchId) {
  const [state, setState] = useState({ match: null, raw: null, loading: true, error: null })
  const [tick, setTick] = useState(0)
  const statusRef = useRef(null)

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
          adapted.home_yellow_cards = res.home_yellow_cards
          adapted.away_yellow_cards = res.away_yellow_cards
          adapted.home_red_cards = res.home_red_cards
          adapted.away_red_cards = res.away_red_cards
          // home_team_id + away_team_id forwarded so the player-events
          // section can filter scorers/cards into the right side without
          // string-matching team names. player_stats is the array
          // populated by services.match_player_stats_service.
          adapted.home_team_id = res.home_team_id
          adapted.away_team_id = res.away_team_id
          adapted.player_stats = res.player_stats || []
          adapted.explanationText = res.prediction?.explanation_text || null
        }
        statusRef.current = adapted?.status || null
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

  // Auto-refresh loop. Re-arms after every fetch (keyed off `tick` and
  // `state.match` so a status change from SCHEDULED → LIVE → FT picks the
  // right cadence on the very next interval).
  useEffect(() => {
    if (!matchId) return undefined

    const isLive = statusRef.current === 'LIVE'
    const interval = isLive ? LIVE_POLL_MS : IDLE_POLL_MS

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
        // Tab just regained focus — refetch immediately so the user sees
        // current data without waiting for the next interval.
        bumpTick()
      }
    }

    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [matchId, tick, state.match])

  return { ...state, reload: () => setTick((t) => t + 1) }
}
