/**
 * frontend/src/services/api.js
 * Axios client for the CupCast API.
 *
 * Base URL is set from VITE_API_URL env var (injected at build time).
 * In local dev, vite.config.js proxies /api to localhost:8000 so
 * VITE_API_URL can be left empty (uses relative paths).
 *
 * All functions return the response data directly (not the Axios response).
 * Errors are propagated — callers should handle with try/catch or
 * React Query's error handling.
 *
 * API functions mirror the backend endpoint structure exactly.
 */

import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || ''

const client = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Extract meaningful error messages from API responses
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.code === 'ECONNABORTED') {
      error.message = 'Request timed out. The server may be slow or unavailable.'
    } else if (!error.response) {
      error.message = 'Unable to reach the server. Check your connection.'
    } else if (error.response.status === 404) {
      error.message = 'The requested resource was not found.'
    } else if (error.response.status >= 500) {
      error.message = 'Server error. Please try again later.'
    } else if (error.response.data?.detail) {
      error.message = error.response.data.detail
    }
    return Promise.reject(error)
  }
)

// ---- Matches ----

/**
 * Fetch upcoming scheduled matches.
 * Returns: { matches: MatchSummary[], total: int, league_filter, days_ahead }
 */
export const getUpcomingMatches = async (league = null, daysAhead = 7) => {
  const params = { days_ahead: daysAhead }
  if (league) params.league = league
  const response = await client.get('/matches/upcoming', { params })
  return response.data
}

/**
 * Fetch a single match with full detail.
 * Returns: MatchDetail (MatchSummary + home_form, away_form, h2h_last_5)
 */
export const getMatch = async (matchId) => {
  const response = await client.get(`/matches/${matchId}`)
  return response.data
}

/**
 * Fetch recent match results.
 * Returns: { matches: MatchSummary[], total: int, prediction_accuracy: float|null }
 */
export const getResults = async (league = null, daysBack = 7) => {
  const params = { days_back: daysBack }
  if (league) params.league = league
  const response = await client.get('/matches/results', { params })
  return response.data
}

// ---- Predictions ----

/**
 * Fetch value picks (matches where model disagrees with bookmakers).
 * Returns: ValuePickResponse[]
 */
export const getValuePicks = async (league = null, minEdge = 0.08) => {
  const params = { min_edge: minEdge }
  if (league) params.league = league
  const response = await client.get('/predictions/value-picks', { params })
  return response.data
}

// ---- Leagues ----

/**
 * Fetch all active leagues.
 * Returns: LeagueResponse[] — { id, code, name, country, season_format, is_active }
 */
export const getLeagues = async () => {
  const response = await client.get('/leagues/')
  return response.data
}

// ---- World Cup ----

/**
 * Fetch all group tables with predictions.
 * Returns: { groups: { A: {...}, B: {...}, ... }, total_groups: int }
 */
export const getWorldCupGroups = async () => {
  const response = await client.get('/worldcup/groups')
  return response.data
}

/**
 * Fetch knockout bracket.
 * Returns: { round_of_32: [...], note: string }
 */
export const getWorldCupBracket = async () => {
  const response = await client.get('/worldcup/bracket')
  return response.data
}

/**
 * Fetch tournament winner odds.
 * Returns: { teams: [{ team_name, win_probability, fifa_rank, total_points }], note }
 */
export const getWorldCupWinnerOdds = async () => {
  const response = await client.get('/worldcup/winner-odds')
  return response.data
}

// ---- Model Performance ----

/**
 * Fetch model accuracy metrics.
 * Returns: ModelPerformanceResponse
 */
export const getModelPerformance = async () => {
  const response = await client.get('/model/performance')
  return response.data
}

/**
 * Fetch individual match predictions for a specific date.
 * Returns: { date, total, correct, wrong, accuracy, matches: [...] }
 */
export const getDailyPredictions = async (dateStr) => {
  const response = await client.get(`/model/performance/daily/${dateStr}`)
  return response.data
}

export default client
