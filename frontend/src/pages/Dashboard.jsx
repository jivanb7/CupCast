import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getUpcomingMatches, getResults } from '../services/api'
import FeaturedPrediction from '../components/match/FeaturedPrediction'
import CountryCard from '../components/ui/CountryCard'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import { matchToCountrySlug } from '../utils/countryMap'

/**
 * Dashboard — landing hub.
 * Fetches today's upcoming matches + recent results, picks the
 * highest-confidence match in the next 24h as Featured, and renders
 * KPIs + country exploration tiles.
 */

const COUNTRY_DEFINITIONS = [
  { slug: 'england', name: 'England', subLabel: 'Premier League' },
  { slug: 'spain', name: 'Spain', subLabel: 'La Liga' },
  { slug: 'italy', name: 'Italy', subLabel: 'Serie A' },
  { slug: 'germany', name: 'Germany', subLabel: 'Bundesliga' },
  { slug: 'france', name: 'France', subLabel: 'Ligue 1' },
  { slug: 'rest', name: 'Rest of World', subLabel: 'MLS · UCL · World Cup' },
]

function isToday(dateStr) {
  const today = new Date().toLocaleDateString('en-CA') // YYYY-MM-DD in local
  return dateStr === today
}

function pickFeatured(matches) {
  if (!matches?.length) return null
  const now = Date.now()
  const cutoff = now + 24 * 60 * 60 * 1000

  const candidates = matches.filter((m) => {
    if (!m.prediction || m.status === 'completed') return false
    if (!m.match_date) return false
    const time = m.kickoff_time && m.kickoff_time !== 'nan' && m.kickoff_time !== 'NaN'
      ? m.kickoff_time : '12:00'
    const dt = new Date(`${m.match_date}T${time}:00Z`).getTime()
    if (Number.isNaN(dt)) return false
    return dt >= now - 2 * 60 * 60 * 1000 && dt <= cutoff
  })

  if (!candidates.length) return null
  return candidates.reduce((best, m) =>
    (m.prediction.confidence ?? 0) > (best.prediction.confidence ?? 0) ? m : best
  )
}

function KpiTile({ label, value, sub, accent = false, tooltip = null }) {
  const [showTooltip, setShowTooltip] = useState(false)
  return (
    <div
      className={`relative rounded-[12px] px-4 py-3.5 bg-card border ${accent ? 'border-accent-gold/30' : 'border-white/6'}`}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className={`cc-label ${accent ? 'text-accent-gold' : ''}`}>{label}</span>
        {tooltip && (
          <button
            type="button"
            className="w-3.5 h-3.5 rounded-full border border-foreground-muted text-foreground-muted text-[9px] font-bold italic font-serif inline-flex items-center justify-center hover:border-accent-gold hover:text-accent-gold cursor-help"
            onMouseEnter={() => setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
            onFocus={() => setShowTooltip(true)}
            onBlur={() => setShowTooltip(false)}
            aria-label={`More info: ${label}`}
          >
            i
          </button>
        )}
      </div>
      <div className={`text-3xl font-extrabold tracking-[-0.03em] text-tabular ${accent ? 'text-accent-gold' : 'text-foreground'}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-foreground-muted mt-0.5">{sub}</div>}

      {tooltip && showTooltip && (
        <div
          className="absolute right-2 top-full mt-2 z-10 w-[230px] rounded-lg border border-white/12 bg-elevated px-3 py-2.5 text-[11px] text-foreground leading-relaxed shadow-xl"
          role="tooltip"
        >
          {tooltip}
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const [matches, setMatches] = useState([])
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchData = useCallback((showSpinner = true) => {
    if (showSpinner) {
      setLoading(true)
      setError(null)
    }
    // 60d window so the Rest-of-World card (MLS + UCL + WC) has data —
    // WC fixtures don't start until June 11 and MLS schedules ~30d ahead.
    // Per-country cards still bucket by date themselves.
    Promise.all([
      getUpcomingMatches(null, 60),
      getResults(null, 7),
    ])
      .then(([upcomingData, resultsData]) => {
        setMatches(upcomingData.matches || [])
        setResults(resultsData.matches || [])
        setError(null)
        setLoading(false)
      })
      .catch((err) => {
        if (showSpinner) setError(err.message)
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    fetchData(true)
    const interval = setInterval(() => fetchData(false), 60000)
    return () => clearInterval(interval)
  }, [fetchData])

  const featured = pickFeatured(matches)
  const todayMatches = matches.filter((m) => isToday(m.match_date))
  const todayCount = todayMatches.length
  const valuePicks = todayMatches.filter((m) => m.prediction?.is_value_pick).length

  // Today's accuracy from completed matches with a prediction
  const todayResults = results.filter(
    (m) => isToday(m.match_date) && m.prediction?.was_correct != null
  )
  const todayCorrect = todayResults.filter((m) => m.prediction.was_correct).length
  const todayAccuracy = todayResults.length > 0
    ? Math.round((todayCorrect / todayResults.length) * 100)
    : null

  // Bucket matches by country for the cards. The Matches page uses a richer
  // slug vocabulary (usa / ucl / world-cup as separate filters), but the
  // Dashboard collapses them all into a single "Rest of World" tile —
  // remap on the fly here rather than touching the shared countryMap util.
  const SLUG_TO_TILE = {
    england: 'england', spain: 'spain', italy: 'italy',
    germany: 'germany', france: 'france',
    usa: 'rest', ucl: 'rest', 'world-cup': 'rest', rest: 'rest',
  }
  const counts = COUNTRY_DEFINITIONS.reduce((acc, c) => {
    acc[c.slug] = { todayCount: 0, upcomingCount: 0 }
    return acc
  }, {})
  matches.forEach((m) => {
    const rawSlug = matchToCountrySlug(m)
    const tileSlug = SLUG_TO_TILE[rawSlug] || 'rest'
    if (!counts[tileSlug]) return
    if (isToday(m.match_date)) counts[tileSlug].todayCount += 1
    else counts[tileSlug].upcomingCount += 1
  })

  const countryData = COUNTRY_DEFINITIONS.map((c) => ({
    ...c,
    todayCount: counts[c.slug].todayCount,
    upcomingCount: counts[c.slug].upcomingCount,
  }))

  if (loading && !matches.length) {
    return (
      <div className="flex justify-center pt-32">
        <LoadingSpinner size="lg" label="Loading dashboard" />
      </div>
    )
  }

  return (
    <div className="max-w-[1180px] mx-auto px-4 sm:px-6 lg:px-12 pt-24 pb-12">
      {error && !matches.length && (
        <div className="cc-card p-6 mb-6 text-center">
          <p className="text-accent-red">{error}</p>
        </div>
      )}

      <FeaturedPrediction match={featured} />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 mb-5">
        <KpiTile label="Today's Matches" value={todayCount} />
        <KpiTile
          label="Today's Accuracy"
          value={todayAccuracy != null ? `${todayAccuracy}%` : '--'}
          sub={todayResults.length > 0 ? `${todayCorrect}/${todayResults.length} evaluated` : 'No games evaluated yet'}
          accent
        />
        <KpiTile
          label="Value Picks Found"
          value={valuePicks}
          sub="From today's fixtures"
          tooltip="Matches where our model's probability exceeds the bookmaker's by at least 8%. Mathematically favorable bets."
        />
      </div>

      <h2 className="text-[20px] font-bold tracking-[-0.01em] mb-3.5">Explore by country</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {countryData.map((c) => (
          <CountryCard key={c.slug} country={c} />
        ))}
      </div>

      <div className="text-center mt-6">
        <Link
          to="/matches?tab=today"
          className="inline-block px-6 py-2.5 rounded-[10px] bg-elevated border border-white/12 text-foreground text-sm font-semibold transition-colors hover:bg-elevated/80 hover:border-accent-gold/30"
        >
          See all {todayCount > 0 ? `${todayCount} games today` : 'matches'} →
        </Link>
      </div>
    </div>
  )
}
