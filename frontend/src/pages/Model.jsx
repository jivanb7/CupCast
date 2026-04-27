// Model Performance — Direction B (Bloomberg terminal)
// Wired to live backend (`useModelPerformance`, `useRecentMatches`).
// Panels the backend doesn't expose (calibration, confusion, deciles,
// market/naive/random comparisons, ROI, Brier) fall back to honest
// "metric not exposed" / `emptyState('calibrating')` copy rather than
// fabricating numbers.

import React from 'react'
import { Link } from 'react-router-dom'
import Aurora from '../components/cc/Aurora'
import Eyebrow from '../components/cc/Eyebrow'
import CCNav from '../components/cc/CCNav'
import UpdatedBadge from '../components/cc/UpdatedBadge'
import useCountUp from '../hooks/useCountUp'
import useCCTheme from '../hooks/useCCTheme'
import useClock from '../hooks/useClock'
import useModelPerformance from '../hooks/useModelPerformance'
import useRecentMatches from '../hooks/useRecentMatches'
import { emptyState } from '../lib/reasons'

const DASH = '—'

export default function Model() {
  const [theme, setTheme] = useCCTheme()
  const tick = useClock(9)
  const { data, loading, error } = useModelPerformance()
  const { matches: recent, loading: recentLoading, error: recentError } = useRecentMatches({ daysBack: 14 })

  const fatal = error || (!loading && !data)

  return (
    <div className={`cc-root cc-${theme} cc-terminal`} style={{position:'relative', minHeight:'100vh', overflowX:'hidden'}}>
      <Aurora/>
      {/* Header */}
      <header style={{position:'relative', zIndex: 5, display:'grid', gridTemplateColumns:'auto 1fr auto auto', gap: 24, alignItems:'center', padding:'12px 24px', borderBottom:'1px solid var(--cc-line-strong)', background:'rgba(2,6,23,0.6)', backdropFilter:'blur(12px)'}}>
        <Link to="/" style={{fontFamily:'var(--cc-serif)', fontStyle:'italic', fontWeight:700, fontSize: 20, color:'var(--cc-gold)', letterSpacing:'-0.02em', textDecoration:'none'}}>CupCast<span style={{color:'var(--cc-muted)', fontStyle:'normal', fontWeight:400, fontSize: 11, marginLeft: 8, fontFamily:'var(--cc-mono)', letterSpacing:'0.1em'}}>// MODEL.PERFORMANCE</span></Link>
        <div className="mono" style={{fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.12em'}}>{headerLine(data, loading, fatal)}</div>
        <CCNav active="Model" theme={theme} onTheme={setTheme}/>
        <UpdatedBadge sec={tick}/>
      </header>

      <div style={{position:'relative', zIndex: 2, padding: 0}}>
        {/* Hero accuracy strip */}
        <section style={{display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr 1fr', borderBottom:'1px solid var(--cc-line-strong)'}}>
          <HeroAccuracy data={data} loading={loading} fatal={fatal}/>
          <PanelStat label="Brier score" v={DASH} sub="metric not exposed yet"/>
          <PanelStat label="Log loss" v={fatal || !data ? DASH : data.logLoss.toFixed(3)} sub={fatal ? 'feed unavailable' : 'lower is better'}/>
          <PanelStat label="ROI · value picks" v={DASH} sub="metric not exposed yet" gold/>
        </section>

        {/* Charts grid */}
        <section style={{display:'grid', gridTemplateColumns:'1.4fr 1fr', borderBottom:'1px solid var(--cc-line-strong)'}}>
          <Panel title={`ROLLING ACCURACY · LAST ${data?.lastWeek?.length || 0} DAYS`} right={data ? `${data.accuracy.toFixed(1)}% SEASON` : ''}>
            <RollingChart data={data?.lastWeek || []} fatal={fatal} loading={loading}/>
          </Panel>
          <Panel title="CALIBRATION · BUCKETED">
            <EmptyPanel kind="calibrating"/>
          </Panel>
        </section>

        {/* League breakdown table */}
        <section style={{display:'grid', gridTemplateColumns:'1.4fr 1fr', borderBottom:'1px solid var(--cc-line-strong)'}}>
          <Panel title="PER-LEAGUE BREAKDOWN" right="SORT · ACCURACY ↓" noPad>
            <LeagueTable rows={data?.perLeague || []} fatal={fatal} loading={loading}/>
          </Panel>
          <Panel title="OUTCOME CONFUSION · LAST 30D" noPad>
            <EmptyPanel kind="calibrating"/>
          </Panel>
        </section>

        {/* Decile + recent calls */}
        <section style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', borderBottom:'1px solid var(--cc-line-strong)'}}>
          <Panel title="ACCURACY BY CONFIDENCE DECILE">
            <EmptyPanel kind="calibrating"/>
          </Panel>
          <Panel title="MODEL VS BASELINES">
            <BigCompare modelAcc={data?.accuracy ?? null}/>
          </Panel>
          <Panel title="RECENT CALLS · LAST 8" noPad>
            <RecentCalls matches={recent} loading={recentLoading} error={recentError}/>
          </Panel>
        </section>

        <footer style={{padding:'14px 24px', display:'flex', justifyContent:'space-between', fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.1em', textTransform:'uppercase'}}>
          <span>← <Link to="/" style={{color:'inherit'}}>Back to Dashboard</Link></span>
          <span>Model · Live performance · backend `/model/performance` + `/matches/results`</span>
        </footer>
      </div>
    </div>
  )
}

function headerLine(data, loading, fatal) {
  if (loading) return 'LOADING MODEL METRICS …'
  if (fatal || !data) return 'MODEL FEED UNAVAILABLE'
  const days = data.lastWeek?.length || 0
  return `${data.accuracy.toFixed(1)}% ACCURACY · ${days}D WINDOW · F1 ${data.f1Macro.toFixed(3)} · LOG LOSS ${data.logLoss.toFixed(3)}`
}

function HeroAccuracy({ data, loading, fatal }) {
  // Hooks must run unconditionally — animate to real value or 0 fallback.
  const target = !loading && !fatal && data ? data.accuracy : 0
  const v = useCountUp(target, { duration: 1100 })
  const showReal = !loading && !fatal && data
  const delta = data?.accuracyDelta ?? 0
  const deltaPositive = delta >= 0

  return (
    <div style={{padding:'28px 32px', borderRight:'1px solid var(--cc-line-strong)', position:'relative'}}>
      <Eyebrow>Season Accuracy</Eyebrow>
      <div style={{display:'flex', alignItems:'baseline', gap: 16, marginTop: 8}}>
        <div className="serif tnum" style={{fontSize: 152, fontStyle:'italic', fontWeight:600, letterSpacing:'-0.05em', lineHeight: 0.9}}>
          {showReal ? v.toFixed(1) : DASH}
        </div>
        <div className="serif" style={{fontSize: 60, fontStyle:'italic', color:'var(--cc-muted)', fontWeight:500}}>%</div>
        <div style={{flex:1}}>
          {showReal ? (
            <>
              <div className="mono" style={{fontSize: 11, color: deltaPositive ? 'var(--cc-green)' : 'var(--cc-red)', letterSpacing:'0.06em'}}>
                {deltaPositive ? '▲' : '▼'} {deltaPositive ? '+' : ''}{delta} pp · 7D vs SEASON
              </div>
              <div className="mono" style={{fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.06em', marginTop: 4}}>
                F1 {data.f1Macro.toFixed(3)} · LOG LOSS {data.logLoss.toFixed(3)}
              </div>
            </>
          ) : (
            <div className="mono" style={{fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.06em'}}>
              {fatal ? emptyState('error') : 'LOADING …'}
            </div>
          )}
        </div>
      </div>
      {/* progress strip — fills proportional to current accuracy */}
      <div style={{display:'flex', gap: 4, marginTop: 18, height: 4}}>
        {Array.from({length: 60}).map((_, i) => (
          <div key={i} style={{flex: 1, background: showReal && i < Math.round((data.accuracy/100)*60) ? 'var(--cc-gold)' : 'var(--cc-line-strong)'}}/>
        ))}
      </div>
      <div className="mono" style={{display:'flex', justifyContent:'space-between', fontSize: 10, color:'var(--cc-dim)', letterSpacing:'0.08em', marginTop: 6}}>
        <span>0%</span><span>25%</span><span>50%</span><span>75%</span><span style={{color:'var(--cc-gold)'}}>100%</span>
      </div>
    </div>
  )
}

function PanelStat({ label, v, sub, trend, gold }) {
  return (
    <div style={{padding:'28px 24px', borderRight:'1px solid var(--cc-line-strong)'}}>
      <Eyebrow>{label}</Eyebrow>
      <div className="serif tnum" style={{fontSize: 64, fontStyle:'italic', fontWeight:600, color: gold ? 'var(--cc-gold)' : 'var(--cc-text)', letterSpacing:'-0.04em', lineHeight: 1, marginTop: 8}}>{v}</div>
      <div className="mono" style={{fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.06em', marginTop: 6}}>{sub}</div>
      {trend && (
        <div className="mono" style={{fontSize: 11, color: trend.startsWith('+') ? 'var(--cc-green)' : 'var(--cc-red)', letterSpacing:'0.06em', marginTop: 6}}>{trend.startsWith('+') ? '▲' : '▼'} {trend} vs prior</div>
      )}
    </div>
  )
}

function Panel({ title, right, children, noPad }) {
  return (
    <div style={{borderRight:'1px solid var(--cc-line-strong)', display:'flex', flexDirection:'column'}}>
      <div style={{display:'flex', justifyContent:'space-between', padding:'12px 18px', borderBottom:'1px solid var(--cc-line)'}}>
        <span className="cc-eyebrow" style={{color:'var(--cc-text)'}}>{title}</span>
        {right && <span className="cc-eyebrow">{right}</span>}
      </div>
      <div style={{flex: 1, padding: noPad ? 0 : 18}}>{children}</div>
    </div>
  )
}

function EmptyPanel({ kind = 'calibrating' }) {
  return (
    <div style={{
      minHeight: 200,
      display:'flex',
      alignItems:'center',
      justifyContent:'center',
      padding: '24px 28px',
      textAlign:'center',
      fontFamily:'var(--cc-serif)',
      fontStyle:'italic',
      fontSize: 16,
      color:'var(--cc-muted)',
      lineHeight: 1.45,
    }}>
      {emptyState(kind)}
    </div>
  )
}

function RollingChart({ data, fatal, loading }) {
  if (loading) {
    return <div style={{minHeight: 220, display:'flex', alignItems:'center', justifyContent:'center', fontFamily:'var(--cc-mono)', fontSize: 11, color:'var(--cc-muted)'}}>LOADING …</div>
  }
  if (fatal) {
    return <EmptyPanel kind="error"/>
  }
  if (!data || data.length < 2) {
    return <EmptyPanel kind="calibrating"/>
  }

  const W = 600, H = 200, P = 16
  const accs = data.map(d => d.acc)
  const rawMin = Math.min(...accs)
  const rawMax = Math.max(...accs)
  // Pad ±10pp around the data, clamp to 0..100
  const min = Math.max(0, Math.floor(rawMin - 10))
  const max = Math.min(100, Math.ceil(rawMax + 10))
  const span = Math.max(1, max - min)
  const x = i => P + i * (W - 2*P) / Math.max(1, data.length - 1)
  const y = v => P + (1 - (v - min) / span) * (H - 2*P)
  const dPath = data.map((d,i) => `${i===0?'M':'L'}${x(i)},${y(d.acc)}`).join(' ')
  const area = `${dPath} L${x(data.length-1)},${H-P} L${x(0)},${H-P} Z`

  // Pick 4 evenly spaced gridlines inside [min, max]
  const gridlines = []
  const step = span / 4
  for (let i = 1; i <= 3; i++) {
    gridlines.push(Math.round(min + step * i))
  }

  const last = data[data.length - 1]
  const first = data[0]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%', height: 220, display:'block'}}>
      <defs>
        <linearGradient id="cc-mp-area" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#F59E0B" stopOpacity="0.25"/>
          <stop offset="100%" stopColor="#F59E0B" stopOpacity="0"/>
        </linearGradient>
      </defs>
      {gridlines.map(g => (
        <g key={g}>
          <line x1={P} x2={W-P} y1={y(g)} y2={y(g)} stroke="var(--cc-line)" strokeDasharray="2 4"/>
          <text x={W-P+4} y={y(g)+3} fill="var(--cc-dim)" fontSize="9" fontFamily="var(--cc-mono)">{g}</text>
        </g>
      ))}
      <path d={area} fill="url(#cc-mp-area)"/>
      <path d={dPath} stroke="var(--cc-gold)" strokeWidth="1.5" fill="none"/>
      {data.map((d, i) => (
        <circle key={i} cx={x(i)} cy={y(d.acc)} r="2.5" fill="var(--cc-gold)"/>
      ))}
      <circle cx={x(data.length-1)} cy={y(last.acc)} r="3.5" fill="var(--cc-gold)" stroke="var(--cc-bg)" strokeWidth="1.5"/>
      <text x={x(data.length-1)-6} y={y(last.acc)-8} textAnchor="end" fill="var(--cc-gold)" fontSize="11" fontFamily="var(--cc-mono)">{last.acc}%</text>
      <text x={P} y={H-4} fill="var(--cc-dim)" fontSize="9" fontFamily="var(--cc-mono)">{first.d || `D-${data.length-1}`}</text>
      <text x={W-P} y={H-4} textAnchor="end" fill="var(--cc-dim)" fontSize="9" fontFamily="var(--cc-mono)">{last.d || 'TODAY'}</text>
    </svg>
  )
}

function LeagueTable({ rows, fatal, loading }) {
  if (loading) {
    return <div style={{padding: 18, fontFamily:'var(--cc-mono)', fontSize: 11, color:'var(--cc-muted)'}}>LOADING …</div>
  }
  if (fatal) return <EmptyPanel kind="error"/>
  if (!rows || rows.length === 0) return <EmptyPanel kind="calibrating"/>

  return (
    <div>
      <div style={{display:'grid', gridTemplateColumns:'2fr 1fr 1fr 1.2fr', padding:'10px 18px', borderBottom:'1px solid var(--cc-line)', fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.1em'}}>
        <span>LEAGUE</span><span style={{textAlign:'right'}}>ACC %</span><span style={{textAlign:'right'}}>N · 7D</span><span style={{textAlign:'right'}}>Δ 7D</span>
      </div>
      {rows.map((r, i) => {
        const hasDelta = r.delta != null
        const positive = hasDelta && r.delta >= 0
        const deltaColor = !hasDelta
          ? 'var(--cc-muted)'
          : positive ? 'var(--cc-green)' : 'var(--cc-red)'
        const arrow = !hasDelta ? '' : positive ? '▲ ' : '▼ '
        const deltaText = !hasDelta
          ? DASH
          : `${arrow}${positive ? '+' : ''}${r.delta.toFixed(1)}`
        return (
          <div key={r.code || i} style={{display:'grid', gridTemplateColumns:'2fr 1fr 1fr 1.2fr', padding:'12px 18px', borderBottom:'1px solid var(--cc-line)', alignItems:'center'}}>
            <span style={{display:'flex', alignItems:'center', gap: 8}}>
              <span style={{width: 6, height: 6, borderRadius: 1, background: i===0 ? 'var(--cc-gold)' : 'var(--cc-line-strong)'}}/>
              <span style={{fontFamily:'var(--cc-mono)', fontSize: 11, letterSpacing:'0.06em'}}>{r.flag} {r.name || r.code}</span>
            </span>
            <span style={{textAlign:'right'}}>
              <span className="serif tnum" style={{fontSize: 22, fontStyle:'italic', fontWeight: 600, color: i===0 ? 'var(--cc-gold)' : 'var(--cc-text)'}}>{r.acc.toFixed(1)}</span>
              <span className="mono" style={{fontSize: 10, color:'var(--cc-muted)', marginLeft: 2}}>%</span>
            </span>
            <span className="mono tnum" style={{textAlign:'right', fontSize: 11, color:'var(--cc-muted)'}}>
              {r.nRecent > 0 ? r.nRecent : DASH}
            </span>
            <span className="mono tnum" style={{textAlign:'right', fontSize: 11, color: deltaColor}}>
              {deltaText}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function BigCompare({ modelAcc }) {
  const rows = [
    { label: 'Model accuracy', value: modelAcc, color: 'gold' },
    { label: 'Market implied',  value: null, color: 'muted' },
    { label: 'Naive home',      value: null, color: 'dim' },
    { label: 'Random',          value: null, color: 'dim' },
  ]
  return (
    <div style={{padding:'10px 0'}}>
      {rows.map((row, i) => {
        const hasValue = row.value != null
        const labelColor = row.color === 'gold' ? 'var(--cc-gold)' : 'var(--cc-muted)'
        const valueColor = row.color === 'gold' ? 'var(--cc-gold)' : row.color === 'muted' ? 'var(--cc-text)' : 'var(--cc-muted)'
        const barColor = row.color === 'gold' ? 'var(--cc-gold)' : row.color === 'muted' ? 'var(--cc-muted)' : 'var(--cc-dim)'
        return (
          <div key={i} style={{padding:'10px 0', borderBottom: i<rows.length-1 ? '1px solid var(--cc-line)' : 'none'}}>
            <div style={{display:'flex', justifyContent:'space-between', marginBottom: 6}}>
              <span className="mono" style={{fontSize: 11, color: labelColor, letterSpacing:'0.08em'}}>{row.label}</span>
              <span className="serif tnum" style={{fontSize: 18, fontStyle:'italic', fontWeight: 600, color: valueColor}}>
                {hasValue ? `${row.value.toFixed(1)}%` : DASH}
              </span>
            </div>
            <div style={{height: 3, background:'var(--cc-line)'}}>
              {hasValue && (
                <div style={{height:'100%', width: `${row.value}%`, background: barColor}}/>
              )}
            </div>
            {!hasValue && (
              <div className="mono" style={{fontSize: 9, color:'var(--cc-dim)', letterSpacing:'0.08em', marginTop: 4}}>
                BASELINE NOT EXPOSED
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function RecentCalls({ matches, loading, error }) {
  if (loading) {
    return <div style={{padding: 18, fontFamily:'var(--cc-mono)', fontSize: 11, color:'var(--cc-muted)'}}>LOADING …</div>
  }
  if (error) return <EmptyPanel kind="error"/>

  // Only finished matches with scores can be evaluated
  const finished = (matches || [])
    .filter(m => m.status === 'FT' && typeof m.score === 'string' && m.score.includes('-'))
    .slice(0, 8)

  if (finished.length === 0) return <EmptyPanel kind="calibrating"/>

  return (
    <div>
      {finished.map((m, i) => {
        const [hg, ag] = m.score.split('-').map(n => Number(n))
        const actualKey = Number.isFinite(hg) && Number.isFinite(ag)
          ? (hg > ag ? 'H' : hg < ag ? 'A' : 'D')
          : null
        const correct = actualKey != null && m.callKey === actualKey
        const callLabel = m.callKey === 'D' ? 'DRAW' : m.callKey === 'H' ? 'HOME' : 'AWAY'
        const actualLabel = actualKey === 'D' ? 'DRAW' : actualKey === 'H' ? 'HOME' : actualKey === 'A' ? 'AWAY' : DASH
        const matchLabel = `${m.home || m.homeShort || '?'} vs ${m.away || m.awayShort || '?'}`
        return (
          <div key={m.id || i} style={{display:'grid', gridTemplateColumns:'1fr 50px 50px 30px 60px', padding:'10px 18px', borderBottom: i<finished.length-1 ? '1px solid var(--cc-line)' : 'none', alignItems:'center', fontFamily:'var(--cc-mono)', fontSize: 11, gap: 4}}>
            <span style={{color:'var(--cc-text)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}} title={matchLabel}>{matchLabel}</span>
            <span style={{color:'var(--cc-muted)'}}>{callLabel}</span>
            <span style={{color:'var(--cc-muted)'}}>{actualLabel}</span>
            <span style={{color: correct ? 'var(--cc-green)' : 'var(--cc-red)', fontSize: 14}}>{correct ? '✓' : '✗'}</span>
            <span className="tnum" style={{textAlign:'right', color:'var(--cc-muted)'}}>{m.score}</span>
          </div>
        )
      })}
    </div>
  )
}
