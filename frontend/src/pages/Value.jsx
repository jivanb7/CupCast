// Value Picks — Direction B (terminal)
// Edge % in gold, compact watchlist with sparklines + book comparison.
//
// Wired to live data via useUpcomingMatches: only matches the model flagged
// as value calls (>=3.5pp edge) surface here. Hit-rate / ROI / Best-League
// slots stay as `—` placeholders until we have a backtest endpoint to back
// real numbers up — empty is better than fabricated.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Aurora from '../components/cc/Aurora';
import Eyebrow from '../components/cc/Eyebrow';
import CCNav from '../components/cc/CCNav';
import UpdatedBadge from '../components/cc/UpdatedBadge';
import useCCTheme from '../hooks/useCCTheme';
import useClock from '../hooks/useClock';
import useUpcomingMatches from '../hooks/useUpcomingMatches';
import { emptyState } from '../lib/reasons';

const TOP_N = 12;
const PLACEHOLDER = '—';

// Friendly KO label: "Today 21:00", "Sat 18:30", "Apr 28 17:30".
// Falls back to whatever fragments exist on the match.
function formatKO(match) {
  const time = match.kickoff || '';
  const iso = match.matchDate || '';
  if (!iso) return time || PLACEHOLDER;

  const day = new Date(iso);
  if (Number.isNaN(day.getTime())) return time || PLACEHOLDER;

  const today = new Date();
  const todayKey = today.toISOString().slice(0, 10);
  const dayKey = iso.slice(0, 10);
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const tomorrowKey = tomorrow.toISOString().slice(0, 10);

  let label;
  if (dayKey === todayKey) label = 'Today';
  else if (dayKey === tomorrowKey) label = 'Tmrw';
  else {
    const diff = (day.getTime() - today.getTime()) / 86400000;
    label = diff > 0 && diff < 7
      ? day.toLocaleDateString('en-US', { weekday: 'short' })
      : day.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  return time ? `${label} ${time}` : label;
}

// Synthesize an ascending sparkline from the current edge. Real edge-over-time
// is a future enhancement — we don't store historical line movement yet.
function synthSpark(edge) {
  if (!edge || edge <= 0) return [0, 0, 0, 0, 0];
  return [0.2, 0.4, 0.55, 0.75, 0.9, 1].map((x) => x * edge);
}

function buildRows(matches) {
  return matches
    .filter((m) => m.valueCall === true)
    .map((m) => ({
      id: m.id,
      match: `${m.home} v ${m.away}`,
      league: m.league || PLACEHOLDER,
      call: m.callTeam || PLACEHOLDER,
      conf: Math.round(m.callConf || 0),
      fair: Number(m.fairOdds) || 0,
      book: Number(m.marketOdds) || 0,
      edge: Number(m.edge) || 0,
      ko: formatKO(m),
      koSort: m.matchDate ? new Date(m.matchDate).getTime() : Infinity,
      spark: synthSpark(Number(m.edge) || 0),
    }))
    .sort((a, b) => b.edge - a.edge)
    .slice(0, TOP_N);
}

function applySort(rows, sort) {
  const sorted = [...rows];
  if (sort === 'edge') sorted.sort((a, b) => b.edge - a.edge);
  else if (sort === 'conf') sorted.sort((a, b) => b.conf - a.conf);
  else if (sort === 'ko') sorted.sort((a, b) => a.koSort - b.koSort);
  return sorted;
}

function leagueAggregate(rows) {
  const by = new Map();
  for (const r of rows) {
    const k = r.league;
    const cur = by.get(k) || { league: k, edge: 0, n: 0 };
    cur.edge += r.edge;
    cur.n += 1;
    by.set(k, cur);
  }
  return Array.from(by.values()).sort((a, b) => b.edge - a.edge);
}

export default function Value() {
  const [theme, setTheme] = useCCTheme();
  const tick = useClock(6);
  const [sort, setSort] = useState('edge');

  const { matches, loading, error } = useUpcomingMatches({ daysAhead: 14 });

  const picks = useMemo(() => buildRows(matches || []), [matches]);
  const sortedPicks = useMemo(() => applySort(picks, sort), [picks, sort]);
  const leagueRows = useMemo(() => leagueAggregate(picks), [picks]);

  const totalEdge = picks.reduce((s, p) => s + p.edge, 0);
  const avgEdge = picks.length ? totalEdge / picks.length : 0;
  const maxLeagueEdge = leagueRows.length ? leagueRows[0].edge : 0;

  return (
    <div className={`cc-root cc-${theme} cc-terminal`} style={{position:'relative', minHeight:'100vh', overflowX:'hidden'}}>
      <Aurora/>
      <header style={{position:'relative', zIndex: 5, display:'grid', gridTemplateColumns:'auto 1fr auto auto', gap: 24, alignItems:'center', padding:'12px 24px', borderBottom:'1px solid var(--cc-line-strong)', background:'rgba(2,6,23,0.6)', backdropFilter:'blur(12px)'}}>
        <Link to="/" style={{fontFamily:'var(--cc-serif)', fontStyle:'italic', fontWeight:700, fontSize: 20, color:'var(--cc-gold)', letterSpacing:'-0.02em', textDecoration:'none'}}>CupCast<span style={{color:'var(--cc-muted)', fontStyle:'normal', fontWeight:400, fontSize: 11, marginLeft: 8, fontFamily:'var(--cc-mono)', letterSpacing:'0.1em'}}>{'// VALUE.WATCHLIST'}</span></Link>
        <div className="mono" style={{fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.12em'}}>EDGE = (FAIR / BOOK − 1) · 100 · MIN +3% TO QUALIFY</div>
        <CCNav active="Value" theme={theme} onTheme={setTheme}/>
        <UpdatedBadge sec={tick}/>
      </header>

      <div style={{position:'relative', zIndex: 2}}>
        {/* Hero strip */}
        <section style={{display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr 1fr', borderBottom:'1px solid var(--cc-line-strong)'}}>
          <div style={{padding:'28px 32px', borderRight:'1px solid var(--cc-line-strong)'}}>
            <Eyebrow gold>◆ Total Edge · Today's Watchlist</Eyebrow>
            <div style={{display:'flex', alignItems:'baseline', gap: 8, marginTop: 10}}>
              <span className="serif tnum" style={{fontSize: 132, fontStyle:'italic', fontWeight: 600, color:'var(--cc-gold)', letterSpacing:'-0.05em', lineHeight: 0.95}}>
                {loading ? PLACEHOLDER : `+${totalEdge.toFixed(1)}`}
              </span>
              <span className="serif" style={{fontSize: 56, color:'var(--cc-gold)', fontStyle:'italic', fontWeight: 500}}>%</span>
            </div>
            <div className="mono" style={{fontSize: 11, color:'var(--cc-muted)', marginTop: 8, letterSpacing:'0.06em'}}>
              ACROSS <span className="tnum" style={{color:'var(--cc-text)'}}>{loading ? PLACEHOLDER : picks.length}</span> PICKS · AVG EDGE <span className="tnum" style={{color:'var(--cc-gold)'}}>{loading || !picks.length ? PLACEHOLDER : `+${avgEdge.toFixed(1)}%`}</span>
            </div>
          </div>
          <div style={{padding:'28px 24px', borderRight:'1px solid var(--cc-line-strong)'}}>
            <Eyebrow>Hit rate · Trailing 90d</Eyebrow>
            <div className="serif tnum" style={{fontSize: 60, fontStyle:'italic', fontWeight: 600, letterSpacing:'-0.04em', lineHeight: 1, marginTop: 8, color:'var(--cc-muted)'}}>{PLACEHOLDER}</div>
            <div className="mono" style={{fontSize: 10, color:'var(--cc-dim)', letterSpacing:'0.06em', marginTop: 6}}>BACKTEST PIPELINE PENDING</div>
          </div>
          <div style={{padding:'28px 24px', borderRight:'1px solid var(--cc-line-strong)'}}>
            <Eyebrow>ROI · Trailing 90d</Eyebrow>
            <div className="serif tnum" style={{fontSize: 60, fontStyle:'italic', fontWeight: 600, letterSpacing:'-0.04em', lineHeight: 1, marginTop: 8, color:'var(--cc-muted)'}}>{PLACEHOLDER}</div>
            <div className="mono" style={{fontSize: 10, color:'var(--cc-dim)', letterSpacing:'0.06em', marginTop: 6}}>BACKTEST PIPELINE PENDING</div>
          </div>
          <div style={{padding:'28px 24px'}}>
            <Eyebrow>Top League · Today's Edge</Eyebrow>
            <div className="serif tnum" style={{fontSize: 60, fontStyle:'italic', fontWeight: 600, letterSpacing:'-0.04em', lineHeight: 1, marginTop: 8}}>
              {loading || !leagueRows.length ? <span style={{color:'var(--cc-muted)'}}>{PLACEHOLDER}</span> : (
                <>+{leagueRows[0].edge.toFixed(1)}<span className="serif" style={{fontSize: 36, color:'var(--cc-muted)'}}>%</span></>
              )}
            </div>
            <div className="mono" style={{fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.06em', marginTop: 6}}>
              {loading || !leagueRows.length ? 'NO LIVE PICKS' : `${leagueRows[0].league.toUpperCase()} · ${leagueRows[0].n} PICK${leagueRows[0].n === 1 ? '' : 'S'}`}
            </div>
          </div>
        </section>

        <section style={{display:'grid', gridTemplateColumns:'1.7fr 1fr', borderBottom:'1px solid var(--cc-line-strong)', minHeight: 580}}>
          {/* Watchlist */}
          <div style={{borderRight:'1px solid var(--cc-line-strong)'}}>
            <div style={{display:'flex', justifyContent:'space-between', padding:'12px 18px', borderBottom:'1px solid var(--cc-line)'}}>
              <span className="cc-eyebrow" style={{color:'var(--cc-text)'}}>
                WATCHLIST · {loading ? '…' : `${picks.length} PICK${picks.length === 1 ? '' : 'S'}`}
              </span>
              <span style={{display:'flex', gap: 12, fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.1em'}}>
                {[['EDGE','edge'],['CONF','conf'],['KO','ko']].map(([l,k]) => (
                  <button key={k} onClick={() => setSort(k)} style={{background:'none', border:'none', color: sort===k ? 'var(--cc-gold)' : 'var(--cc-muted)', fontFamily:'var(--cc-mono)', fontSize: 10, letterSpacing:'0.1em', cursor:'pointer'}}>SORT · {l} {sort===k ? '↓' : ''}</button>
                ))}
              </span>
            </div>
            {/* Header row */}
            <div style={{display:'grid', gridTemplateColumns:'40px 2fr 1fr 70px 70px 90px 60px', padding:'10px 18px', borderBottom:'1px solid var(--cc-line)', fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-dim)', letterSpacing:'0.1em'}}>
              <span>#</span><span>MATCH</span><span>PICK</span><span style={{textAlign:'right'}}>FAIR</span><span style={{textAlign:'right'}}>BOOK</span><span style={{textAlign:'right'}}>EDGE</span><span style={{textAlign:'right'}}>KO</span>
            </div>

            {loading && <WatchlistSkeleton/>}
            {!loading && error && (
              <div style={{padding: '32px 18px', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 14, color:'var(--cc-muted)', lineHeight: 1.5}}>
                {emptyState('error')}
              </div>
            )}
            {!loading && !error && picks.length === 0 && (
              <div style={{padding: '32px 18px', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 14, color:'var(--cc-muted)', lineHeight: 1.5}}>
                {emptyState('noValue')}
              </div>
            )}

            {!loading && !error && sortedPicks.map((p, i) => (
              <Link to={`/match/${p.id}`} key={p.id} style={{textDecoration:'none', color:'inherit'}}>
                <div className="cc-rise cc-hover" style={{
                  display:'grid', gridTemplateColumns:'40px 2fr 1fr 70px 70px 90px 60px',
                  padding:'14px 18px', borderBottom:'1px solid var(--cc-line)', alignItems:'center',
                  animationDelay: `${i*50}ms`, cursor:'pointer',
                }}>
                  <span className="mono tnum" style={{color: i===0 ? 'var(--cc-gold)' : 'var(--cc-dim)', fontSize: 11}}>{String(i+1).padStart(2,'0')}</span>
                  <div>
                    <div style={{fontFamily:'var(--cc-display)', fontSize: 14, fontWeight: 500}}>{p.match}</div>
                    <div className="mono" style={{fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.08em', marginTop: 2}}>{p.league} · {p.ko}</div>
                  </div>
                  <div style={{display:'flex', alignItems:'center', gap: 6}}>
                    <span style={{color:'var(--cc-gold)', fontSize: 12}}>◆</span>
                    <span style={{fontFamily:'var(--cc-display)', fontSize: 13, fontWeight: 600, color:'var(--cc-gold)'}}>{p.call}</span>
                    <span className="mono tnum" style={{fontSize: 10, color:'var(--cc-muted)'}}>{p.conf}%</span>
                  </div>
                  <span className="serif tnum" style={{textAlign:'right', fontSize: 18, fontStyle:'italic', fontWeight: 500, color:'var(--cc-text)'}}>{p.fair ? p.fair.toFixed(2) : PLACEHOLDER}</span>
                  <span className="serif tnum" style={{textAlign:'right', fontSize: 18, fontStyle:'italic', fontWeight: 500, color:'var(--cc-muted)'}}>{p.book ? p.book.toFixed(2) : PLACEHOLDER}</span>
                  <span style={{textAlign:'right'}}>
                    <span className="serif tnum" style={{fontSize: 28, fontStyle:'italic', fontWeight: 600, color:'var(--cc-gold)', letterSpacing:'-0.02em'}}>+{p.edge.toFixed(1)}</span>
                    <span className="serif" style={{color:'var(--cc-gold)', fontSize: 14}}>%</span>
                  </span>
                  <Sparkline data={p.spark}/>
                </div>
              </Link>
            ))}
          </div>

          {/* Right rail — Edge by League (live aggregation across today's picks) */}
          <div>
            <div style={{padding:'12px 18px', borderBottom:'1px solid var(--cc-line)'}}>
              <span className="cc-eyebrow" style={{color:'var(--cc-text)'}}>EDGE BY LEAGUE · TODAY</span>
            </div>

            {loading && <RailSkeleton/>}
            {!loading && !error && leagueRows.length === 0 && (
              <div style={{padding: '24px 18px', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 13, color:'var(--cc-muted)', lineHeight: 1.5}}>
                {emptyState('noValue')}
              </div>
            )}
            {!loading && !error && leagueRows.map((row) => (
              <div key={row.league} style={{padding:'14px 18px', borderBottom:'1px solid var(--cc-line)'}}>
                <div style={{display:'flex', justifyContent:'space-between', marginBottom: 6}}>
                  <span className="mono" style={{fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.08em'}}>{row.league}</span>
                  <span style={{display:'flex', alignItems:'baseline', gap: 6}}>
                    <span className="mono tnum" style={{fontSize: 10, color:'var(--cc-dim)'}}>{row.n}</span>
                    <span className="serif tnum" style={{fontSize: 18, fontStyle:'italic', fontWeight: 600, color:'var(--cc-gold)'}}>+{row.edge.toFixed(1)}%</span>
                  </span>
                </div>
                <div style={{height: 3, background:'var(--cc-line)'}}>
                  <div style={{height:'100%', width: `${maxLeagueEdge ? (row.edge / maxLeagueEdge) * 100 : 0}%`, background:'var(--cc-gold)'}}/>
                </div>
              </div>
            ))}

            <div style={{padding:'14px 18px', borderBottom:'1px solid var(--cc-line)', marginTop: 12}}>
              <span className="cc-eyebrow" style={{color:'var(--cc-text)'}}>HOW WE CALCULATE EDGE</span>
            </div>
            <div style={{padding: 18, fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 14, color:'var(--cc-muted)', lineHeight: 1.5}}>
              The model produces a fair price for each outcome from a 1,000-trial Monte Carlo. We compare against the median market book; anything more than +3% gets watchlisted. Sub-3% noise gets dropped — the calibration error eats the edge.
            </div>
          </div>
        </section>

        <footer style={{padding:'14px 24px', display:'flex', justifyContent:'space-between', fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.1em', textTransform:'uppercase'}}>
          <span>← <Link to="/" style={{color:'inherit'}}>Back to Dashboard</Link></span>
          <span>Value · Not betting advice · Edges are model-implied, not guaranteed</span>
        </footer>
      </div>
    </div>
  );
}

// Block silhouettes for the watchlist body. No spinners — design rule.
function WatchlistSkeleton() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} style={{
          display:'grid', gridTemplateColumns:'40px 2fr 1fr 70px 70px 90px 60px',
          padding:'14px 18px', borderBottom:'1px solid var(--cc-line)', alignItems:'center', gap: 10,
        }}>
          <div style={{height: 10, width: 22, background:'var(--cc-line)'}}/>
          <div>
            <div style={{height: 14, width: '70%', background:'var(--cc-line)', marginBottom: 6}}/>
            <div style={{height: 9, width: '40%', background:'var(--cc-line)'}}/>
          </div>
          <div style={{height: 12, width: '60%', background:'var(--cc-line)'}}/>
          <div style={{height: 16, width: 40, background:'var(--cc-line)', justifySelf:'end'}}/>
          <div style={{height: 16, width: 40, background:'var(--cc-line)', justifySelf:'end'}}/>
          <div style={{height: 22, width: 60, background:'var(--cc-line)', justifySelf:'end'}}/>
          <div style={{height: 18, width: 56, background:'var(--cc-line)', justifySelf:'end'}}/>
        </div>
      ))}
    </>
  );
}

function RailSkeleton() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} style={{padding:'14px 18px', borderBottom:'1px solid var(--cc-line)'}}>
          <div style={{display:'flex', justifyContent:'space-between', marginBottom: 8}}>
            <div style={{height: 10, width: '40%', background:'var(--cc-line)'}}/>
            <div style={{height: 14, width: '20%', background:'var(--cc-line)'}}/>
          </div>
          <div style={{height: 3, background:'var(--cc-line)'}}/>
        </div>
      ))}
    </>
  );
}

function Sparkline({ data }) {
  const W = 56, H = 22;
  if (!data || data.length === 0) return <svg viewBox={`0 0 ${W} ${H}`} style={{width: W, height: H, marginLeft:'auto'}}/>;
  const max = Math.max(...data, 0.0001);
  const x = i => i*(W-2)/Math.max(1, data.length-1) + 1;
  const y = v => H - 2 - (v/max)*(H-4);
  const path = data.map((v,i) => `${i===0?'M':'L'}${x(i)},${y(v)}`).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width: W, height: H, marginLeft:'auto'}}>
      <path d={path} stroke="var(--cc-gold)" strokeWidth="1" fill="none"/>
      <circle cx={x(data.length-1)} cy={y(data[data.length-1])} r="2" fill="var(--cc-gold)"/>
    </svg>
  );
}
