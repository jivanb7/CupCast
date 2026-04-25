import { useState, useEffect, useMemo, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getUpcomingMatches, getResults } from '../services/api'
import MatchRow from '../components/match/MatchRow'
import LeagueFilterBar from '../components/ui/LeagueFilterBar'
import Pagination from '../components/ui/Pagination'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import { matchToCountrySlug } from '../utils/countryMap'

const PAGE_SIZE = 10
const VALID_TABS = ['today', 'upcoming', 'recent']
const VALID_WINDOWS = ['7', '30', 'season']
const WINDOW_DAYS = { '7': 7, '30': 30, season: 365 }

function isToday(dateStr) {
  return dateStr === new Date().toLocaleDateString('en-CA')
}

function formatTimeChip(utcTime, dateStr) {
  if (!utcTime || utcTime === 'nan' || utcTime === 'NaN') return 'TBD'
  const d = dateStr || new Date().toISOString().slice(0, 10)
  const dt = new Date(`${d}T${utcTime}:00Z`)
  if (isNaN(dt.getTime())) return 'TBD'
  return dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
}

function formatDateHeader(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })
}

function dayDeltaLabel(dateStr) {
  if (!dateStr) return ''
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(dateStr + 'T00:00:00')
  const diff = Math.round((d - today) / (24 * 60 * 60 * 1000))
  if (diff === 1) return 'tomorrow'
  if (diff === 0) return 'today'
  if (diff < 0) return null
  return null
}

function groupBy(arr, keyFn) {
  const map = new Map()
  arr.forEach((item) => {
    const k = keyFn(item)
    if (!map.has(k)) map.set(k, [])
    map.get(k).push(item)
  })
  return [...map.entries()]
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`px-4 py-2 text-sm font-semibold rounded-[7px] transition-colors cursor-pointer ${
        active ? 'bg-accent-gold text-deep' : 'text-foreground-muted hover:text-foreground'
      }`}
    >
      {children}
    </button>
  )
}

function TimeChipDivider({ time, count, label }) {
  return (
    <div className="flex items-center gap-2.5 mt-4 mb-2">
      <span className="text-[11px] text-accent-gold font-bold tracking-[0.04em]">{label || time}</span>
      <span className="flex-1 h-px bg-white/5" />
      {count != null && (
        <span className="text-[10px] text-foreground-muted/70">
          {count} {count === 1 ? 'fixture' : 'fixtures'}
        </span>
      )}
    </div>
  )
}

function DateHeader({ dateStr, count }) {
  const delta = dayDeltaLabel(dateStr)
  return (
    <div className="text-[13px] font-bold text-foreground mt-4 mb-2 flex items-baseline gap-2">
      <span>{formatDateHeader(dateStr)}</span>
      <span className="text-[11px] font-medium text-foreground-muted">
        {delta ? `· ${delta} · ` : '· '}
        {count} {count === 1 ? 'fixture' : 'fixtures'}
      </span>
    </div>
  )
}

function EmptyState({ children }) {
  return (
    <div className="rounded-[12px] border border-white/6 bg-card/60 p-8 text-center text-sm text-foreground-muted">
      {children}
    </div>
  )
}

export default function Matches() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = VALID_TABS.includes(searchParams.get('tab')) ? searchParams.get('tab') : 'today'
  const country = searchParams.get('country') || null
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10))
  const timeWindow = VALID_WINDOWS.includes(searchParams.get('window'))
    ? searchParams.get('window')
    : '7'

  const [upcoming, setUpcoming] = useState([])
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const updateParams = useCallback((updates) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      Object.entries(updates).forEach(([k, v]) => {
        if (v == null || v === '' || (k === 'tab' && v === 'today')) next.delete(k)
        else next.set(k, v)
      })
      return next
    }, { replace: true })
  }, [setSearchParams])

  const setTab = useCallback((t) => updateParams({ tab: t, page: null }), [updateParams])
  const setCountry = useCallback((c) => updateParams({ country: c, page: null }), [updateParams])
  const setPage = useCallback((p) => updateParams({ page: p === 1 ? null : p }), [updateParams])
  const setWindow = useCallback((w) => updateParams({ window: w === '7' ? null : w, page: null }), [updateParams])

  // Fetch data based on tab
  const fetchData = useCallback((showSpinner = true) => {
    if (showSpinner) {
      setLoading(true)
      setError(null)
    }
    if (tab === 'recent') {
      getResults(null, WINDOW_DAYS[timeWindow] || 7)
        .then((data) => {
          setResults(data.matches || [])
          setError(null)
          setLoading(false)
        })
        .catch((err) => {
          if (showSpinner) setError(err.message)
          setLoading(false)
        })
    } else {
      // 60-day window so WC fixtures (kickoff Jun 11) appear on the WC pill
      // and the "Rest of World" meta-filter, instead of silently empty.
      getUpcomingMatches(null, 60)
        .then((data) => {
          setUpcoming(data.matches || [])
          setError(null)
          setLoading(false)
        })
        .catch((err) => {
          if (showSpinner) setError(err.message)
          setLoading(false)
        })
    }
  }, [tab, timeWindow])

  useEffect(() => {
    fetchData(true)
    const interval = setInterval(() => fetchData(false), 60000)
    return () => clearInterval(interval)
  }, [fetchData])

  // Apply country filter. The "Rest of World" pill is a meta-filter that
  // covers any match outside the Big-5 leagues — i.e. USA (MLS), UCL, and
  // World Cup. Strict equality on every other slug.
  const REST_SLUGS = ['usa', 'ucl', 'world-cup', 'rest']
  const filterByCountry = useCallback((arr) => {
    if (!country) return arr
    if (country === 'rest') {
      return arr.filter((m) => REST_SLUGS.includes(matchToCountrySlug(m)))
    }
    return arr.filter((m) => matchToCountrySlug(m) === country)
  }, [country])

  const todayList = useMemo(() => {
    return filterByCountry(upcoming.filter((m) => isToday(m.match_date)))
      .sort((a, b) => (a.kickoff_time || '').localeCompare(b.kickoff_time || ''))
  }, [upcoming, filterByCountry])

  const upcomingList = useMemo(() => {
    const today = new Date().toLocaleDateString('en-CA')
    return filterByCountry(upcoming.filter((m) => m.match_date > today))
      .sort((a, b) => {
        if (a.match_date !== b.match_date) return a.match_date.localeCompare(b.match_date)
        return (a.kickoff_time || '').localeCompare(b.kickoff_time || '')
      })
  }, [upcoming, filterByCountry])

  const recentList = useMemo(() => {
    return filterByCountry(results.filter((m) => m.status === 'completed'))
      .sort((a, b) => b.match_date.localeCompare(a.match_date))
  }, [results, filterByCountry])

  // Recent KPIs (server returns prediction_accuracy but we want client-side
  // numbers consistent with whatever filter the user has applied)
  const evaluated = recentList.filter((m) => m.prediction?.was_correct != null)
  const correct = evaluated.filter((m) => m.prediction.was_correct).length
  const wrong = evaluated.length - correct
  const accuracy = evaluated.length > 0 ? Math.round((correct / evaluated.length) * 100) : null

  // Pagination for upcoming + recent
  const paginatedList = tab === 'upcoming'
    ? upcomingList
    : tab === 'recent' ? recentList : todayList
  const pageCount = tab === 'today' ? 1 : Math.max(1, Math.ceil(paginatedList.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount)
  const pageStart = (safePage - 1) * PAGE_SIZE
  const pageItems = tab === 'today'
    ? paginatedList
    : paginatedList.slice(pageStart, pageStart + PAGE_SIZE)

  const titleSub = tab === 'today'
    ? `${formatDateHeader(new Date().toLocaleDateString('en-CA'))} · ${todayList.length} ${todayList.length === 1 ? 'fixture' : 'fixtures'} today`
    : tab === 'upcoming'
      ? `Fixtures from tomorrow onwards · ${upcomingList.length} matches`
      : 'Completed matches with our prediction vs the actual result'

  return (
    <div className="max-w-[1180px] mx-auto px-4 sm:px-6 lg:px-12 pt-24 pb-12">
      {/* page header */}
      <div className="flex justify-between items-end mb-4 gap-4 flex-wrap">
        <div>
          <h1 className="text-[28px] font-extrabold tracking-[-0.02em] mb-1">Matches</h1>
          <p className="text-[13px] text-foreground-muted">{titleSub}</p>
        </div>
        <div role="tablist" aria-label="Match views" className="inline-flex bg-base border border-white/6 rounded-[10px] p-1">
          <TabButton active={tab === 'today'} onClick={() => setTab('today')}>Today</TabButton>
          <TabButton active={tab === 'upcoming'} onClick={() => setTab('upcoming')}>Upcoming</TabButton>
          <TabButton active={tab === 'recent'} onClick={() => setTab('recent')}>Recent</TabButton>
        </div>
      </div>

      {/* Recent KPI row */}
      {tab === 'recent' && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mb-3.5">
            <div className="rounded-[10px] border border-white/6 bg-card px-4 py-3">
              <div className="cc-label">Games Evaluated</div>
              <div className="text-2xl font-extrabold tracking-[-0.03em] text-tabular">{evaluated.length}</div>
              <div className="text-[10px] text-foreground-muted mt-0.5">
                {timeWindow === '7' ? 'Last 7 days' : timeWindow === '30' ? 'Last 30 days' : 'This season'}
              </div>
            </div>
            <div className="rounded-[10px] border border-white/6 bg-card px-4 py-3">
              <div className="cc-label text-accent-green">Correct</div>
              <div className="text-2xl font-extrabold tracking-[-0.03em] text-accent-green text-tabular">{correct}</div>
            </div>
            <div className="rounded-[10px] border border-white/6 bg-card px-4 py-3">
              <div className="cc-label text-accent-red">Wrong</div>
              <div className="text-2xl font-extrabold tracking-[-0.03em] text-accent-red text-tabular">{wrong}</div>
            </div>
            <div className="rounded-[10px] border border-accent-gold/30 bg-card px-4 py-3">
              <div className="cc-label text-accent-gold">Accuracy</div>
              <div className="text-2xl font-extrabold tracking-[-0.03em] text-accent-gold text-tabular">
                {accuracy != null ? `${accuracy}%` : '--'}
              </div>
            </div>
          </div>

          {/* Time-window pills */}
          <div className="flex flex-wrap items-center gap-1.5 mb-3">
            {[
              { v: '7', label: 'Last 7 days' },
              { v: '30', label: 'Last 30 days' },
              { v: 'season', label: 'This season' },
            ].map(({ v, label }) => (
              <button
                key={v}
                type="button"
                onClick={() => setWindow(v)}
                aria-pressed={timeWindow === v}
                className={`px-3 py-[5px] rounded-full text-xs border transition-colors cursor-pointer ${
                  timeWindow === v
                    ? 'bg-accent-gold text-deep border-accent-gold font-semibold'
                    : 'bg-card text-foreground-muted border-white/8 hover:text-foreground hover:border-white/15'
                }`}
              >
                {label}
              </button>
            ))}
            <span aria-hidden className="inline-block w-px h-5 bg-white/10 mx-1" />
          </div>
        </>
      )}

      <LeagueFilterBar value={country} onChange={setCountry} />

      {/* Loading */}
      {loading && pageItems.length === 0 && (
        <div className="flex justify-center py-16">
          <LoadingSpinner size="lg" label="Loading matches" />
        </div>
      )}

      {error && pageItems.length === 0 && (
        <div className="cc-card p-8 text-center">
          <p className="text-accent-red">{error}</p>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Today view: grouped by kickoff time */}
          {tab === 'today' && (
            todayList.length === 0 ? (
              <EmptyState>
                No matches today{country ? ' for this filter' : ''} — try the Upcoming tab.
              </EmptyState>
            ) : (
              groupBy(todayList, (m) => formatTimeChip(m.kickoff_time, m.match_date))
                .map(([time, items]) => (
                  <div key={time}>
                    <TimeChipDivider label={time} count={items.length} />
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {items.map((m) => <MatchRow key={m.id} match={m} variant="today" />)}
                    </div>
                  </div>
                ))
            )
          )}

          {/* Upcoming view: paginated, grouped by date inside the page */}
          {tab === 'upcoming' && (
            upcomingList.length === 0 ? (
              <EmptyState>
                No upcoming matches{country ? ' for this filter' : ''}.
              </EmptyState>
            ) : (
              <>
                {groupBy(pageItems, (m) => m.match_date).map(([date, items]) => (
                  <div key={date}>
                    <DateHeader dateStr={date} count={items.length} />
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {items.map((m) => <MatchRow key={m.id} match={m} variant="upcoming" />)}
                    </div>
                  </div>
                ))}
                <Pagination page={safePage} pageCount={pageCount} onPageChange={setPage} />
                {pageCount > 1 && (
                  <div className="text-center text-[11px] text-foreground-muted/70 mt-1.5">
                    Showing {pageStart + 1}–{Math.min(pageStart + PAGE_SIZE, upcomingList.length)} of {upcomingList.length} · {PAGE_SIZE} per page
                  </div>
                )}
              </>
            )
          )}

          {/* Recent view: flat paginated list */}
          {tab === 'recent' && (
            recentList.length === 0 ? (
              <EmptyState>
                No completed matches in this window{country ? ' for this filter' : ''}.
              </EmptyState>
            ) : (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {pageItems.map((m) => <MatchRow key={m.id} match={m} variant="recent" />)}
                </div>
                <Pagination page={safePage} pageCount={pageCount} onPageChange={setPage} />
                {pageCount > 1 && (
                  <div className="text-center text-[11px] text-foreground-muted/70 mt-1.5">
                    Showing {pageStart + 1}–{Math.min(pageStart + PAGE_SIZE, recentList.length)} of {recentList.length} · {PAGE_SIZE} per page
                  </div>
                )}
              </>
            )
          )}
        </>
      )}
    </div>
  )
}
