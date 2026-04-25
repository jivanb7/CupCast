import { Component, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getWcOverview,
  getWcGroups,
  getWcFixtures,
  getWcTitleOdds,
  getWcOpeningMatch,
} from '../services/api'
import WCHero from '../components/worldcup/WCHero'
import StageProgressStrip from '../components/worldcup/StageProgressStrip'
import TitleContenders from '../components/worldcup/TitleContenders'
import PredictedWinnerBlock from '../components/worldcup/PredictedWinnerBlock'
import GroupCard from '../components/worldcup/GroupCard'
import OpeningMatchPrediction from '../components/worldcup/OpeningMatchPrediction'
import FeaturedPrediction from '../components/match/FeaturedPrediction'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import Tabs, { TabPanel } from '../components/ui/Tabs'

/**
 * WorldCup — landing hub for the FIFA World Cup 2026 tournament.
 *
 * Two tabs share the same fetched payload (cheap; data is cached server-side).
 * Tab state is mirrored to the URL via the `tab` query string so the view is
 * shareable and refresh-stable.
 *
 *   /world-cup                   → defaults to "predictions"
 *   /world-cup?tab=predictions   → predictions panel
 *   /world-cup?tab=groups        → groups & stats panel
 *
 * Each major section is wrapped in a per-section ErrorBoundary so a single
 * failed branch (e.g. Monte Carlo not yet run) doesn't break the whole page.
 */

const VALID_TABS = ['predictions', 'groups']
const DEFAULT_TAB = 'predictions'

class SectionBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-[12px] border border-accent-red/30 bg-accent-red/[0.06] px-5 py-4 mb-4 text-sm">
          <div className="font-bold text-accent-red mb-1">
            {this.props.label || 'Section'} failed to render
          </div>
          <div className="text-foreground-muted text-xs">
            {this.state.error?.message || 'Unknown error'}
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

function pickFeaturedWcMatch(matches) {
  if (!matches?.length) return null
  const now = Date.now()
  const cutoff = now + 72 * 60 * 60 * 1000
  const candidates = matches.filter((m) => {
    if (!m.prediction || m.status === 'completed') return false
    if (!m.match_date) return false
    const time = m.kickoff_time && m.kickoff_time !== 'nan' ? m.kickoff_time : '12:00'
    const dt = new Date(`${m.match_date}T${time}:00Z`).getTime()
    if (Number.isNaN(dt)) return false
    return dt >= now - 2 * 60 * 60 * 1000 && dt <= cutoff
  })
  if (!candidates.length) {
    const upcoming = matches.filter((m) => m.prediction && m.status !== 'completed')
    if (!upcoming.length) return null
    return upcoming.reduce((best, m) =>
      (m.prediction.confidence ?? 0) > (best.prediction.confidence ?? 0) ? m : best
    )
  }
  return candidates.reduce((best, m) =>
    (m.prediction.confidence ?? 0) > (best.prediction.confidence ?? 0) ? m : best
  )
}

function todayFixtures(matches) {
  if (!matches?.length) return []
  const today = new Date().toLocaleDateString('en-CA') // YYYY-MM-DD local
  return matches.filter((m) => m.match_date === today)
}

/**
 * Helper line above the group grid — explains the color accents used on
 * each row. Matches the convention used elsewhere in the design language
 * (small caps label + colored swatches).
 */
function GroupLegend() {
  const items = [
    { label: 'Advancing', color: '#10b981' },
    { label: 'Best third', color: '#f59e0b' },
    { label: 'Eliminated', color: '#ef4444' },
  ]
  const copy = 'Top 2 advance to knockouts · Best 8 third-placed teams also advance'
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-foreground-muted mt-1">
      <span>{copy}</span>
      <span className="flex items-center gap-2.5">
        {items.map((it) => (
          <span key={it.label} className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: it.color }}
            />
            <span>{it.label}</span>
          </span>
        ))}
      </span>
    </div>
  )
}

export default function WorldCup() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const activeTab = VALID_TABS.includes(tabParam) ? tabParam : DEFAULT_TAB

  const [overview, setOverview] = useState(null)
  const [groupsData, setGroupsData] = useState(null)
  const [fixtures, setFixtures] = useState([])
  const [titleOdds, setTitleOdds] = useState(null)
  const [openingMatch, setOpeningMatch] = useState(null)
  const [loading, setLoading] = useState(true)
  const [topError, setTopError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    Promise.allSettled([
      getWcOverview(),
      getWcGroups(),
      getWcFixtures({ days: 14, includeCompleted: false }),
      getWcTitleOdds(),
      getWcOpeningMatch(),
    ]).then((results) => {
      if (cancelled) return
      const [ov, gr, fx, to, om] = results
      if (ov.status === 'fulfilled') setOverview(ov.value)
      if (gr.status === 'fulfilled') setGroupsData(gr.value)
      if (fx.status === 'fulfilled') setFixtures(fx.value?.matches || [])
      if (to.status === 'fulfilled') setTitleOdds(to.value)
      if (om.status === 'fulfilled') setOpeningMatch(om.value)

      const allFailed = results.every((r) => r.status === 'rejected')
      if (allFailed) {
        setTopError(results[0].reason?.message || 'Failed to load tournament data')
      }
      setLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [])

  const featuredMatch = useMemo(() => pickFeaturedWcMatch(fixtures), [fixtures])
  const today = useMemo(() => todayFixtures(fixtures), [fixtures])

  const oddsAvailable = titleOdds?.available === true
  const champion = oddsAvailable ? titleOdds.most_likely_champion : null
  const contenders = oddsAvailable ? (titleOdds.title_contenders || []) : []

  function handleTabChange(id) {
    const next = new URLSearchParams(searchParams)
    if (id === DEFAULT_TAB) {
      next.delete('tab')
    } else {
      next.set('tab', id)
    }
    setSearchParams(next, { replace: true })
  }

  if (loading) {
    return (
      <div className="flex justify-center pt-32">
        <LoadingSpinner size="lg" label="Loading World Cup hub" />
      </div>
    )
  }

  if (topError && !overview && !groupsData) {
    return (
      <div className="max-w-[1180px] mx-auto px-4 sm:px-6 lg:px-12 pt-24 pb-12">
        <div className="cc-card p-8 text-center">
          <p className="text-accent-red font-semibold mb-2">Unable to load World Cup data</p>
          <p className="text-foreground-muted text-sm">{topError}</p>
        </div>
      </div>
    )
  }

  const kpiTiles = [
    {
      label: 'Matches today',
      value: today.length || (fixtures[0] ? '0' : '—'),
      sub: today.length > 0 ? 'Fixtures kicking off today' : 'Check back closer to a match day',
    },
    {
      label: 'Model accuracy',
      value:
        overview?.model_accuracy_wc != null
          ? `${Math.round(overview.model_accuracy_wc * 100)}%`
          : '—',
      sub:
        overview?.matches_played > 0
          ? `${overview.matches_played} match${overview.matches_played === 1 ? '' : 'es'} graded · WC-only`
          : 'No graded matches yet',
      gold: true,
    },
    {
      label: 'Value picks found',
      value: fixtures.filter((m) => m.prediction?.is_value_pick).length,
      sub: 'Across upcoming WC fixtures',
    },
    {
      label: 'Title contenders',
      value: oddsAvailable ? contenders.length : '—',
      sub: oddsAvailable
        ? 'Mathematically alive in the sim'
        : 'Sim not yet run',
    },
  ]

  const tabs = [
    { id: 'predictions', label: 'Predictions' },
    { id: 'groups', label: 'Groups & Stats' },
  ]

  return (
    <div className="max-w-[1180px] mx-auto px-4 sm:px-6 lg:px-12 pt-24 pb-12">
      <SectionBoundary label="Hero">
        <WCHero overview={overview} />
      </SectionBoundary>

      <SectionBoundary label="Stage progress">
        <StageProgressStrip
          currentStage={overview?.current_stage}
          currentMatchday={overview?.current_matchday}
        />
      </SectionBoundary>

      <Tabs
        tabs={tabs}
        active={activeTab}
        onChange={handleTabChange}
        ariaLabel="World Cup sections"
        className="mt-2"
      />

      <TabPanel id="predictions" active={activeTab}>
        {featuredMatch && (
          <SectionBoundary label="Featured prediction">
            <FeaturedPrediction match={featuredMatch} />
          </SectionBoundary>
        )}

        {oddsAvailable ? (
          <div className="flex flex-col gap-6">
            <SectionBoundary label="Predicted winner">
              <PredictedWinnerBlock
                champion={champion}
                topContenderStats={contenders}
              />
            </SectionBoundary>

            <SectionBoundary label="Title contenders">
              <TitleContenders
                contenders={contenders}
                totalContenders={contenders.length}
              />
            </SectionBoundary>
          </div>
        ) : (
          <div className="rounded-[14px] border border-accent-gold/20 bg-accent-gold/[0.04] px-5 py-4 mb-[18px]">
            <div className="text-accent-gold font-bold text-[13px] tracking-[0.15em] uppercase mb-1.5">
              ◆ Title projections pending
            </div>
            <p className="text-sm text-foreground-muted leading-relaxed">
              Title contenders, our predicted winner, and the projected bracket all
              appear here once the first Monte Carlo simulation runs.
            </p>
            <p className="text-xs text-foreground-muted mt-2 font-mono">
              Admin: <code className="text-accent-gold">POST /api/v1/admin/world-cup/run-simulation</code>
              {titleOdds?.reason && (
                <span className="block text-[11px] text-foreground-muted mt-1">
                  {titleOdds.reason}
                </span>
              )}
            </p>
          </div>
        )}
      </TabPanel>

      <TabPanel id="groups" active={activeTab}>
        {/* KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 mb-[18px]">
          {kpiTiles.map((tile) => (
            <div
              key={tile.label}
              className={`rounded-[12px] px-4 py-3.5 bg-[#111827] border ${
                tile.gold ? 'border-accent-gold/30' : 'border-white/[0.06]'
              }`}
            >
              <div className={`cc-label ${tile.gold ? 'text-accent-gold' : ''}`}>
                {tile.label}
              </div>
              <div
                className={`text-[28px] font-extrabold tracking-[-0.03em] mt-1.5 text-tabular ${
                  tile.gold ? 'text-accent-gold' : 'text-foreground'
                }`}
              >
                {tile.value}
              </div>
              <div className="text-[11px] text-foreground-muted mt-0.5">{tile.sub}</div>
            </div>
          ))}
        </div>

        <SectionBoundary label="Group stage">
          <div>
            <header className="mb-3">
              <h2 className="text-[20px] font-extrabold tracking-[-0.01em]">
                Group Stage — Standings
              </h2>
              <GroupLegend />
            </header>
            {groupsData?.groups?.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {groupsData.groups.map((g) => (
                  <GroupCard key={g.label} group={g} />
                ))}
              </div>
            ) : (
              <div className="cc-card p-8 text-center text-foreground-muted text-sm">
                Group data not yet available.
              </div>
            )}
          </div>
        </SectionBoundary>

        {openingMatch?.available && (
          <SectionBoundary label="Opening match prediction">
            <OpeningMatchPrediction data={openingMatch} />
          </SectionBoundary>
        )}
      </TabPanel>
    </div>
  )
}
