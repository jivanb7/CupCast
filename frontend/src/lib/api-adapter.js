// Maps the backend `MatchSummary` shape (from /api/v1/matches/...) into the
// CC `Match` shape that the design pages consume. Pages can drop this in
// where they currently use the mock `matches` from lib/data.js.
//
// Backend shape (subset that matters):
//   id (int), match_date (date), home_team_name, away_team_name,
//   home_team_short_name?, away_team_short_name?,
//   league_code, league_name, status, match_minute?, kickoff_time?,
//   tournament?, stage?, group_label?,
//   prediction: { prob_home_win, prob_draw, prob_away_win,
//                 predicted_result ('HOME_WIN'|'DRAW'|'AWAY_WIN'),
//                 confidence, is_value_pick, value_pick_direction,
//                 explanation_text, was_correct,
//                 odds_home, odds_draw, odds_away,
//                 edge_home, edge_draw, edge_away }
//   home_goals, away_goals, result
//
// CC shape that decorate() expects:
//   id (string), league, stage, home, homeShort, away, awayShort,
//   kickoff (HH:MM), venue, status (UPCOMING|LIVE|FT), minute?, score?,
//   probH, probD, probA  (0..100, integer, sum to 100),
//   edge (modelProb - marketImpliedProb in pp)

import { decorate } from './data.js'
import { shortFor, shortOverride, venueFor, formatStage, leagueShortFor } from './teamMeta.js'

const STATUS_MAP = {
  scheduled: 'UPCOMING',
  upcoming: 'UPCOMING',
  live: 'LIVE',
  in_play: 'LIVE',
  inplay: 'LIVE',
  ft: 'FT',
  full_time: 'FT',
  finished: 'FT',
  completed: 'FT',
}

// Pick the best available short for a team. Priority:
//   1. curated override (real-world conventions like LIV / RMA / PSG / LAG)
//   2. backend short_name when it's plausibly a code (<=4 chars, not a copy
//      of the full name)
//   3. heuristic derivation
function bestShort(fullName, apiShort) {
  const override = shortOverride(fullName)
  if (override) return override
  if (apiShort && apiShort !== fullName && apiShort.length <= 4 && apiShort.trim()) return apiShort
  return shortFor(fullName)
}

function probsTo100(pH, pD, pA) {
  // Backend probabilities are 0..1 floats. Convert to integer percentages
  // that sum to exactly 100 (largest-remainder rounding).
  const raw = [pH, pD, pA].map((p) => (p == null ? 0 : Number(p) * 100))
  const total = raw.reduce((a, b) => a + b, 0)
  // No prediction available — surface a calibrated "unknown" rather than 1/1/1.
  if (total < 1) return [34, 33, 33]
  const floors = raw.map((v) => Math.floor(v))
  const remainders = raw.map((v, i) => ({ i, frac: v - floors[i] }))
  const drift = 100 - floors.reduce((a, b) => a + b, 0)
  remainders.sort((a, b) => b.frac - a.frac)
  for (let k = 0; k < drift && k < remainders.length; k++) {
    floors[remainders[k].i] += 1
  }
  return floors
}

function pickEdge(pred) {
  if (!pred) return 0
  // Backend stores predicted_result as a single char ('H'|'D'|'A') and the
  // edge fields as decimal fractions. The design uses percentage points.
  const dir = String(pred.predicted_result || '').toUpperCase()
  let raw = 0
  if (dir === 'H' || dir === 'HOME_WIN') raw = pred.edge_home ?? 0
  else if (dir === 'D' || dir === 'DRAW') raw = pred.edge_draw ?? 0
  else if (dir === 'A' || dir === 'AWAY_WIN') raw = pred.edge_away ?? 0
  return +(Number(raw) * 100).toFixed(1)
}

function kickoffHHMM(matchDate, kickoffTime) {
  if (kickoffTime) return String(kickoffTime).slice(0, 5)
  if (matchDate) {
    try {
      const d = new Date(matchDate)
      const hh = String(d.getUTCHours()).padStart(2, '0')
      const mm = String(d.getUTCMinutes()).padStart(2, '0')
      return `${hh}:${mm}`
    } catch {
      return ''
    }
  }
  return ''
}

export function adaptMatch(api) {
  if (!api) return null
  const pred = api.prediction
  const [pH, pD, pA] = probsTo100(
    pred?.prob_home_win,
    pred?.prob_draw,
    pred?.prob_away_win
  )
  const status = STATUS_MAP[String(api.status || '').toLowerCase()] || 'UPCOMING'
  const score = api.home_goals != null && api.away_goals != null
    ? `${api.home_goals}-${api.away_goals}`
    : undefined
  const homeShort = bestShort(api.home_team_name, api.home_team_short_name)
  const awayShort = bestShort(api.away_team_name, api.away_team_short_name)
  const decorated = decorate({
    id: String(api.id),
    league: leagueShortFor(api.league_code, api.league_name),
    leagueCode: api.league_code || '',
    stage: formatStage(api.stage, api.group_label),
    home: api.home_team_name,
    homeShort,
    homeCrest: api.home_team_crest || null,
    away: api.away_team_name,
    awayShort,
    awayCrest: api.away_team_crest || null,
    kickoff: kickoffHHMM(api.match_date, api.kickoff_time),
    matchDate: api.match_date || '',
    venue: venueFor(api.home_team_name),
    status,
    minute: api.match_minute ? Number(String(api.match_minute).replace(/[^0-9]/g, '')) || undefined : undefined,
    score,
    probH: pH,
    probD: pD,
    probA: pA,
    edge: pickEdge(pred),
    wasCorrect: pred?.was_correct ?? null,
    explanationText: pred?.explanation_text || null,
  })

  // Override marketOdds with the real book line when the prediction carries
  // it. decorate() falls back to a synthesized price when odds are missing,
  // which is fine cosmetically but tautological — prefer the real odds.
  const realOddsByKey = {
    H: pred?.odds_home ?? null,
    D: pred?.odds_draw ?? null,
    A: pred?.odds_away ?? null,
  }
  const realCallOdds = realOddsByKey[decorated.callKey]
  if (realCallOdds && realCallOdds > 0) {
    decorated.marketOdds = +Number(realCallOdds).toFixed(2)
  }
  decorated.hasMarketOdds = Boolean(
    realOddsByKey.H || realOddsByKey.D || realOddsByKey.A
  )
  decorated.marketOddsByKey = realOddsByKey
  return decorated
}

export function adaptMatches(apiMatches) {
  return (apiMatches || []).map(adaptMatch).filter(Boolean)
}

// ──────────────────────────────────────────────────────────────────────
// Model performance
// ──────────────────────────────────────────────────────────────────────

const LEAGUE_FLAG_BY_CODE = {
  epl: '🏴', laliga: '🇪🇸', seriea: '🇮🇹', bundesliga: '🇩🇪', ligue1: '🇫🇷',
  ucl: '⭐', eredivisie: '🇳🇱', mls: '🇺🇸', worldcup: '🏆',
  championship: '🏴', league_one: '🏴', league_two: '🏴', national_league: '🏴',
}

// Convert backend's `/model/performance` into the shape the design pages
// already consume (matching the keys originally exposed by lib/data.js).
export function adaptModelPerformance(api) {
  if (!api) return null
  const overallAcc = Number(api.overall_accuracy ?? 0) * 100
  const dates = Array.isArray(api.accuracy_by_date) ? api.accuracy_by_date : []
  const recent = dates.slice(-8) // last 8 days for the form chart
  const lastWeek = recent.map((d) => ({
    d: formatShortDate(d.date),
    acc: Math.round(Number(d.accuracy ?? 0) * 100),
    total: d.total,
  }))

  const leagueAcc = api.accuracy_by_league || {}
  const leagueWindow = api.accuracy_by_league_window || {}
  const perLeague = Object.entries(leagueAcc)
    .map(([code, acc]) => {
      const w = leagueWindow[code]
      return {
        code,
        name: leagueShortFor(code, code),
        flag: LEAGUE_FLAG_BY_CODE[code] || '⚽',
        acc: +(Number(acc) * 100).toFixed(1),
        delta: w?.delta_pp ?? null, // null when either window has no sample
        nRecent: w?.n_recent ?? 0,
        nPrior: w?.n_prior ?? 0,
      }
    })
    .sort((a, b) => b.acc - a.acc)

  // Headline: overall accuracy + a 7-day delta (last vs prior week)
  const sevenDayWindow = lastWeek.slice(-7)
  const recentTotal = sevenDayWindow.reduce((s, d) => s + (d.total || 0), 0)
  const recentCorrect = sevenDayWindow.reduce(
    (s, d) => s + Math.round((d.acc / 100) * (d.total || 0)),
    0
  )
  const recentAcc = recentTotal > 0 ? (recentCorrect / recentTotal) * 100 : overallAcc
  const accuracyDelta = +(recentAcc - overallAcc).toFixed(1)

  return {
    accuracy: +overallAcc.toFixed(1),
    accuracyDelta,
    rolling30: +overallAcc.toFixed(1),
    rolling90: +overallAcc.toFixed(1),
    f1Macro: +(Number(api.overall_f1_macro ?? 0)).toFixed(3),
    logLoss: +(Number(api.overall_log_loss ?? 0)).toFixed(3),
    lastWeek,
    perLeague,
  }
}

function formatShortDate(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch {
    return String(iso).slice(5)
  }
}
