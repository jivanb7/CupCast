import { useEffect, useState } from 'react'
import {
  getWcOverview,
  getWcGroups,
  getWcTitleOdds,
  getWcFixtures,
} from '../services/api'

// Pulls every WC endpoint we need for the page in one shot:
//   - overview (dates, host countries, totals, current stage)
//   - groups (12 groups with team standings)
//   - title-odds (per-team title / final / semi / qf / r16 / r32 chances)
//   - fixtures (upcoming WC matches for the bracket / counters)
//
// Returns a unified `{ data, loading, error, reload }` triple. `data` has
// `{ overview, groups, titleOdds, fixtures, oddsByTeamId }` once it
// resolves; intermediate failures of any single endpoint surface in the
// `data` object as `null` for that slot so the page can render partial.
export default function useWorldCup() {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    Promise.all([
      getWcOverview().catch(() => null),
      getWcGroups().catch(() => null),
      getWcTitleOdds().catch(() => null),
      getWcFixtures({ days: 60, includeCompleted: false }).catch(() => null),
    ])
      .then(([overview, groups, titleOdds, fixtures]) => {
        if (!alive) return
        const oddsByTeamId = {}
        if (titleOdds?.title_contenders) {
          for (const c of titleOdds.title_contenders) oddsByTeamId[c.team_id] = c
        }
        setState({
          data: {
            overview,
            groups: groups?.groups || [],
            titleOdds: titleOdds?.available ? titleOdds : null,
            mostLikelyChampion: titleOdds?.most_likely_champion || null,
            mostLikelyFinals: titleOdds?.most_likely_finals || [],
            fixtures: fixtures?.matches || [],
            oddsByTeamId,
          },
          loading: false,
          error: null,
        })
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
