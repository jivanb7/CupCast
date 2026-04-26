import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { getUpcomingMatches, getResults } from '../services/api'
import FeaturedPrediction from '../components/match/FeaturedPrediction'
import CountryCard from '../components/ui/CountryCard'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import { matchToCountrySlug } from '../utils/countryMap'

import StadiumAurora from '../components/background/StadiumAurora'
import PlayerRail from '../components/dashboard/PlayerRail'

import mbappeImg from '../assets/players/mbappe.webp'
import cr7Img from '../assets/players/cr7.webp'
import messiImg from '../assets/players/messi.webp'
import haalandImg from '../assets/players/haaland.webp'
import kaneImg from '../assets/players/harrykane.webp'
import dembeleImg from '../assets/players/dembele.webp'

const COUNTRY_DEFINITIONS = [
  { slug: 'england', name: 'England', subLabel: 'Premier League' },
  { slug: 'spain', name: 'Spain', subLabel: 'La Liga' },
  { slug: 'italy', name: 'Italy', subLabel: 'Serie A' },
  { slug: 'germany', name: 'Germany', subLabel: 'Bundesliga' },
  { slug: 'france', name: 'France', subLabel: 'Ligue 1' },
  { slug: 'rest', name: 'Rest of World', subLabel: 'MLS · UCL · World Cup' },
]

// Players FLANK the Featured Prediction — top-anchored, descending press row.
// Each player's `w` and `h` track the natural aspect ratio of their photo so
// no figure renders pillar-boxed (Messi's image is landscape, hence wider).
// Sized down overall vs. v1 so heads aren't clipped by the navbar and so
// nobody dominates. Haaland sits forward (highest z) per user direction.
//   w = container width in px (default 240 if omitted)
//   h = container height in vh
// Six players total — three per side, mirror-balanced. Yamal removed.
// Each w/h hand-tuned to the photo's natural aspect (Messi is landscape so
// his container is wider). yVh is from the top of the rail; the bottom row
// (Messi left, Kane right) sits at the same level as a deliberate symmetry.
// Six players total — three per side, mirror-balanced. Yamal removed.
// Bottom row (Messi left, Kane right) sits at the same yVh as deliberate
// symmetry. Heights/widths track each photo's natural aspect — Messi is
// landscape so his container is wider and shorter.
const LEFT_RAIL = [
  { src: mbappeImg,  alt: 'Kylian Mbappé',  tone: 'warm', xPct: 20, yVh: 8,  z: 4, w: 170, h: 28 },
  { src: messiImg,   alt: 'Lionel Messi',   tone: 'warm', xPct: 10, yVh: 34, z: 6, w: 400, h: 26 },
  { src: haalandImg, alt: 'Erling Haaland', tone: 'cool', xPct: 8,  yVh: 42, z: 7, w: 280, h: 46 },
]
const RIGHT_RAIL = [
  { src: cr7Img,     alt: 'Cristiano Ronaldo', tone: 'warm',    xPct: 24, yVh: 4,  z: 5, w: 200, h: 34 },
  { src: dembeleImg, alt: 'Ousmane Dembélé',   tone: 'cool',    xPct: 38, yVh: 38, z: 4, w: 185, h: 28 },
  { src: kaneImg,    alt: 'Harry Kane',        tone: 'warm',    xPct: 18, yVh: 62, z: 3, w: 220, h: 32 },
]

function isToday(dateStr) {
  const today = new Date().toLocaleDateString('en-CA')
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
    <div className="cc-glass-card relative px-4 py-3.5">
      <div className="flex items-center justify-between mb-1.5">
        <span className={`cc-label ${accent ? 'text-accent-gold' : ''}`}>{label}</span>
        {tooltip && (
          <button
            type="button"
            className="w-3.5 h-3.5 rounded-full border cc-content-text-muted text-[9px] font-bold italic font-serif inline-flex items-center justify-center hover:border-accent-gold hover:text-accent-gold cursor-help"
            style={{ borderColor: 'var(--content-text-muted)' }}
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
      <div
        className={`text-3xl font-extrabold tracking-[-0.03em] text-tabular ${accent ? 'text-accent-gold' : 'cc-content-text'}`}
      >
        {value}
      </div>
      {sub && <div className="text-[11px] cc-content-text-muted mt-0.5">{sub}</div>}

      {tooltip && showTooltip && (
        <div
          className="cc-glass-card absolute right-2 top-full mt-2 z-10 w-[230px] px-3 py-2.5 text-[11px] cc-content-text leading-relaxed shadow-xl"
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

  const todayResults = results.filter(
    (m) => isToday(m.match_date) && m.prediction?.was_correct != null
  )
  const todayCorrect = todayResults.filter((m) => m.prediction.was_correct).length
  const todayAccuracy = todayResults.length > 0
    ? Math.round((todayCorrect / todayResults.length) * 100)
    : null

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
      <>
        <StadiumAurora />
        <div className="flex justify-center pt-32 relative z-10">
          <LoadingSpinner size="lg" label="Loading dashboard" />
        </div>
      </>
    )
  }

  return (
    <>
      <StadiumAurora />

      <PlayerRail side="left" players={LEFT_RAIL} />
      <PlayerRail side="right" players={RIGHT_RAIL} />

      <div className="max-w-[1180px] mx-auto px-4 sm:px-6 lg:px-12 pt-20 pb-6 relative z-10">
        {error && !matches.length && (
          <div className="cc-glass-card p-6 mb-6 text-center">
            <p className="text-accent-red">{error}</p>
          </div>
        )}

        {/* HERO — featured prediction (no player center; players live on rails) */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
          className="mb-6"
        >
          <FeaturedPrediction match={featured} />
        </motion.div>

        {/* KPIs */}
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

        <h2 className="text-[20px] font-bold tracking-[-0.01em] mb-3.5 cc-content-text">
          Explore by country
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {countryData.map((c) => (
            <CountryCard key={c.slug} country={c} />
          ))}
        </div>

        <div className="text-center mt-6">
          <Link
            to="/matches?tab=today"
            className="cc-glass-card inline-block px-6 py-2.5 text-sm font-semibold transition-colors hover:border-accent-gold/30 cc-content-text"
          >
            See all {todayCount > 0 ? `${todayCount} games today` : 'matches'} →
          </Link>
        </div>
      </div>
    </>
  )
}
