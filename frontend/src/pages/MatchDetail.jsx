// Match Detail — Direction C
// Editorial scroll-driven page. Score hero → probability split → form & h2h
// → key stats grid → model "why" pull-quote bullets.
//
// All data sourced from `useMatchDetail(matchId)` which returns the
// CC-adapted match plus form / h2h / shots / corners / explanationText
// forwarded from the API. The page renders only what the backend supplies
// — fabricated stats (xG, possession, PPDA) are deliberately omitted.

import Aurora from '../components/cc/Aurora'
import Crest from '../components/cc/Crest'
import Eyebrow from '../components/cc/Eyebrow'
import CCNav from '../components/cc/CCNav'
import UpdatedBadge from '../components/cc/UpdatedBadge'
import SplitWords from '../components/cc/SplitWords'
import useCountUp from '../hooks/useCountUp'
import useCCTheme from '../hooks/useCCTheme'
import useClock from '../hooks/useClock'
import useInView from '../hooks/useInView'
import useMatchDetail from '../hooks/useMatchDetail'
import { pickFor, emptyState } from '../lib/reasons'
import { tzAbbreviation } from '../lib/time'
import { Link, useParams } from 'react-router-dom'

export default function MatchDetail() {
  const [theme, setTheme] = useCCTheme();
  const tick = useClock(8);

  const { matchId } = useParams()
  const { match: m, loading, error } = useMatchDetail(matchId)

  return (
    <div className={`cc-root cc-${theme}`} style={{position:'relative', minHeight:'100vh', overflowX:'hidden'}}>
      <Aurora/>
      <FloatingHeader theme={theme} setTheme={setTheme} tick={tick} active="Match"/>

      <div style={{position:'relative', zIndex: 2, paddingTop: 96, paddingBottom: 80}}>
        {loading && <MDLoading/>}
        {!loading && error && <MDMessage copy={emptyState('error')}/>}
        {!loading && !error && !m && <MDMessage copy={emptyState('noMatches')}/>}
        {!loading && !error && m && (
          <>
            <MDHero m={m}/>
            <MDDivider label="② Probability split"/>
            <MDProbSplit m={m}/>
            <MDDivider label="③ Form & head-to-head"/>
            <MDForm m={m}/>
            <MDDivider label="④ Why we called it"/>
            <MDWhy m={m}/>
            <MDDivider label="⑤ Key stats"/>
            <MDStats m={m}/>
          </>
        )}
        <MDFooter/>
      </div>
    </div>
  );
}

function FloatingHeader({ theme, setTheme, tick, active }) {
  return (
    <header style={{position:'fixed', top: 18, left: 0, right: 0, zIndex: 50, display:'flex', justifyContent:'center', pointerEvents:'none'}}>
      <div style={{
        pointerEvents:'auto', display:'flex', alignItems:'center', gap: 18,
        padding:'10px 18px',
        background: theme==='night' ? 'rgba(2,6,23,0.6)' : 'rgba(241,237,229,0.75)',
        backdropFilter:'blur(14px)',
        border:'1px solid var(--cc-line-strong)', borderRadius: 999,
      }}>
        <Link to="/" style={{fontFamily:'var(--cc-serif)', fontStyle:'italic', fontWeight:700, fontSize: 16, color:'var(--cc-gold)', letterSpacing:'-0.02em', textDecoration:'none'}}>CupCast</Link>
        <span style={{color:'var(--cc-dim)'}}>·</span>
        <CCNav active={active} theme={theme} onTheme={setTheme} compact/>
        <span style={{color:'var(--cc-dim)'}}>·</span>
        <UpdatedBadge sec={tick}/>
      </div>
    </header>
  );
}

// ── Loading / error ────────────────────────────────────────────────────

function MDLoading() {
  return (
    <section style={{maxWidth: 1080, margin:'0 auto', padding:'0 40px 60px'}}>
      <div style={{display:'flex', alignItems:'center', gap: 14, marginBottom: 32, fontFamily:'var(--cc-mono)', fontSize: 11, letterSpacing:'0.16em', color:'var(--cc-muted)', textTransform:'uppercase'}}>
        <span style={{color:'var(--cc-gold)'}}>① The Match</span>
        <span style={{flex: 1, height: 1, background:'var(--cc-line)'}}/>
        <span style={{color:'var(--cc-dim)'}}>Loading…</span>
      </div>
      <div style={{
        display:'grid', gridTemplateColumns:'1fr auto 1fr', gap: 36,
        alignItems:'center', padding:'40px 0',
      }}>
        <div style={{textAlign:'right'}}>
          <SkeletonBlock w={88} h={88} radius={12} style={{display:'inline-block'}}/>
          <SkeletonBlock w={280} h={56} style={{margin:'18px 0 0 auto'}}/>
          <SkeletonBlock w={180} h={11} style={{margin:'18px 0 0 auto'}}/>
        </div>
        <div style={{textAlign:'center'}}>
          <SkeletonBlock w={120} h={120}/>
        </div>
        <div style={{textAlign:'left'}}>
          <SkeletonBlock w={88} h={88} radius={12}/>
          <SkeletonBlock w={280} h={56} style={{marginTop: 18}}/>
          <SkeletonBlock w={180} h={11} style={{marginTop: 18}}/>
        </div>
      </div>
      <SkeletonBlock w="100%" h={56} style={{marginTop: 24, maxWidth: 720, marginLeft:'auto', marginRight:'auto'}}/>
    </section>
  );
}

function SkeletonBlock({ w, h, radius = 6, style }) {
  return (
    <div
      className="cc-pulse"
      style={{
        width: w, height: h, borderRadius: radius,
        background: 'var(--cc-line)',
        ...style,
      }}
    />
  );
}

function MDMessage({ copy }) {
  return (
    <section style={{maxWidth: 720, margin:'0 auto', padding:'80px 40px', textAlign:'center'}}>
      <div className="cc-eyebrow" style={{color:'var(--cc-gold)'}}>◆ The Match</div>
      <p style={{
        marginTop: 16,
        fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 28, lineHeight: 1.4,
        color:'var(--cc-muted)', textWrap:'balance',
      }}>
        {copy}
      </p>
      <Link
        to="/matches"
        style={{
          display:'inline-block', marginTop: 28,
          fontFamily:'var(--cc-mono)', fontSize: 11, letterSpacing:'0.12em', textTransform:'uppercase',
          color:'var(--cc-gold)', textDecoration:'none',
          borderBottom:'1px solid var(--cc-gold)', paddingBottom: 2,
        }}
      >
        Browse all matches →
      </Link>
    </section>
  );
}

// ── Hero ───────────────────────────────────────────────────────────────

function formatFormCount(form) {
  if (!form?.last_5_results || form.last_5_results.length === 0) return null
  const dots = form.last_5_results.join('·')
  return `LAST 5: ${dots}`
}

function MDHero({ m }) {
  const homeFormStr = formatFormCount(m.home_form)
  const awayFormStr = formatFormCount(m.away_form)
  const subtitle = m.explanationText || (m.callTeam
    ? `The model nudges ${m.callTeam} at ${m.callConf}%; the book sits at ${m.marketOdds.toFixed(2)} versus a fair price of ${m.fairOdds.toFixed(2)} — that's the gap we're calling.`
    : 'Probabilities loaded; no headline call to share.')

  return (
    <section style={{maxWidth: 1080, margin:'0 auto', padding:'0 40px 60px'}}>
      <div className="cc-rise" style={{display:'flex', alignItems:'center', gap: 14, marginBottom: 32, fontFamily:'var(--cc-mono)', fontSize: 11, letterSpacing:'0.16em', color:'var(--cc-muted)', textTransform:'uppercase', flexWrap:'wrap'}}>
        <span style={{color:'var(--cc-gold)'}}>① The Match</span>
        <span style={{flex: 1, height: 1, background:'var(--cc-line)', minWidth: 40}}/>
        {m.league && <span>{m.league}{m.stage ? ` · ${m.stage}` : ''}</span>}
        {m.kickoff && <span>{m.kickoffDateLabel ? `${m.kickoffDateLabel} · ${m.kickoff}` : m.kickoff} {tzAbbreviation()}</span>}
        {m.venue && <span style={{color:'var(--cc-text)'}}>{m.venue}</span>}
      </div>

      <div style={{
        display:'grid', gridTemplateColumns:'1fr auto 1fr', gap: 36,
        alignItems:'center', padding:'40px 0',
      }}>
        <div className="cc-rise" style={{textAlign:'right', animationDelay:'80ms'}}>
          <div style={{display:'inline-block'}}>
            <Crest short={m.homeShort} crestUrl={m.homeCrest} color="#FEBE10" size={88}/>
          </div>
          <h1 className="serif" style={{fontSize: 64, fontStyle:'italic', fontWeight:600, letterSpacing:'-0.04em', lineHeight: 1, margin:'18px 0 0', textWrap:'balance'}}>
            {m.home}
          </h1>
          {homeFormStr && (
            <div className="mono" style={{marginTop: 12, fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.1em', textTransform:'uppercase'}}>
              {homeFormStr}
            </div>
          )}
        </div>

        <div className="cc-rise" style={{textAlign:'center', animationDelay:'160ms'}}>
          {m.status === 'LIVE' && m.score ? (
            <>
              <div className="serif tnum" style={{fontSize: 132, fontStyle:'italic', fontWeight:600, color:'var(--cc-text)', letterSpacing:'-0.05em', lineHeight: 1}}>{m.score}</div>
              <div className="mono" style={{marginTop: 6, fontSize: 11, color:'var(--cc-red)', letterSpacing:'0.12em'}}>● LIVE {m.minute ? `${m.minute}'` : ''}</div>
            </>
          ) : m.status === 'FT' && m.score ? (
            <>
              <div className="serif tnum" style={{fontSize: 132, fontStyle:'italic', fontWeight:600, color:'var(--cc-text)', letterSpacing:'-0.05em', lineHeight: 1}}>{m.score}</div>
              <div className="mono" style={{marginTop: 6, fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.12em'}}>FULL TIME</div>
            </>
          ) : (
            <>
              <div className="serif tnum" style={{fontSize: 132, fontStyle:'italic', fontWeight:600, color:'var(--cc-muted)', letterSpacing:'-0.05em', lineHeight: 1}}>vs</div>
              {m.kickoff && (
                <div className="mono" style={{marginTop: 6, fontSize: 11, color:'var(--cc-gold)', letterSpacing:'0.12em'}}>
                  ◆ KO {m.kickoffDateLabel ? `${m.kickoffDateLabel.toUpperCase()} · ${m.kickoff}` : m.kickoff} {tzAbbreviation()}
                </div>
              )}
            </>
          )}
        </div>

        <div className="cc-rise" style={{textAlign:'left', animationDelay:'240ms'}}>
          <div style={{display:'inline-block'}}>
            <Crest short={m.awayShort} crestUrl={m.awayCrest} color="#6CABDD" size={88}/>
          </div>
          <h1 className="serif" style={{fontSize: 64, fontStyle:'italic', fontWeight:600, letterSpacing:'-0.04em', lineHeight: 1, margin:'18px 0 0', textWrap:'balance'}}>
            {m.away}
          </h1>
          {awayFormStr && (
            <div className="mono" style={{marginTop: 12, fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.1em', textTransform:'uppercase'}}>
              {awayFormStr}
            </div>
          )}
        </div>
      </div>

      <div className="cc-rise" style={{animationDelay:'320ms', textAlign:'center', maxWidth: 720, margin:'24px auto 0', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 24, lineHeight: 1.4, color:'var(--cc-muted)'}}>
        <SplitWords delay={400} step={35}>
          {subtitle}
        </SplitWords>
      </div>
    </section>
  );
}

function MDDivider({ label, right }) {
  return (
    <div style={{maxWidth: 1080, margin:'48px auto 24px', padding:'0 40px', display:'flex', alignItems:'center', gap: 22, fontFamily:'var(--cc-mono)', fontSize: 11, letterSpacing:'0.16em', textTransform:'uppercase', color:'var(--cc-muted)'}}>
      <span style={{color:'var(--cc-text)'}}>{label}</span>
      <span style={{flex: 1, height: 1, background:'var(--cc-line)'}}/>
      {right && <span>{right}</span>}
    </div>
  );
}

function MDProbSplit({ m }) {
  const valH = useCountUp(m.probH, { duration: 700, delay: 200 });
  const valD = useCountUp(m.probD, { duration: 700, delay: 300 });
  const valA = useCountUp(m.probA, { duration: 700, delay: 400 });
  const fair = Number.isFinite(m.fairOdds) ? m.fairOdds.toFixed(2) : '—'
  const market = Number.isFinite(m.marketOdds) ? m.marketOdds.toFixed(2) : '—'
  const showEdge = m.valueCall && Number.isFinite(m.edge) && m.edge > 0
  return (
    <section style={{maxWidth: 1080, margin:'0 auto', padding:'0 40px 40px'}}>
      <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', border:'1px solid var(--cc-line-strong)', borderRadius: 8, overflow:'hidden'}}>
        <ProbCellMD label={`${m.home} wins`} sub={m.callKey === 'H' ? '◆ The Call' : null} val={valH} c="var(--cc-green)" highlight={m.callKey === 'H'}/>
        <ProbCellMD label="Draw" sub={m.callKey === 'D' ? '◆ The Call' : null} val={valD} c="var(--cc-amber)" highlight={m.callKey === 'D'}/>
        <ProbCellMD label={`${m.away} wins`} sub={m.callKey === 'A' ? '◆ The Call' : null} val={valA} c="var(--cc-red)" highlight={m.callKey === 'A'}/>
      </div>
      <div style={{display:'flex', justifyContent:'space-between', flexWrap:'wrap', gap: 12, marginTop: 18, fontFamily:'var(--cc-mono)', fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.08em'}}>
        <span>Fair odds: <span className="tnum" style={{color:'var(--cc-text)'}}>{fair}</span> vs book <span className="tnum">{market}</span></span>
        {showEdge && <span style={{color:'var(--cc-gold)'}}>◆ VALUE EDGE +{m.edge}%</span>}
        <span>Confidence: <span className="tnum" style={{color:'var(--cc-text)'}}>{m.callConf}%</span></span>
      </div>
    </section>
  );
}

function ProbCellMD({ label, sub, val, c, highlight }) {
  const intV = Math.round(val);
  return (
    <div style={{padding:'34px 28px', borderRight:'1px solid var(--cc-line)', background: highlight ? 'rgba(245,158,11,0.04)' : 'transparent'}}>
      <Eyebrow>{label}</Eyebrow>
      {sub && <div className="cc-eyebrow" style={{color:'var(--cc-gold)', marginTop: 4}}>{sub}</div>}
      <div style={{display:'flex', alignItems:'baseline', gap: 8, marginTop: 12}}>
        <span className="serif tnum" style={{fontSize: 92, fontStyle:'italic', fontWeight:600, color: highlight ? 'var(--cc-gold)' : 'var(--cc-text)', letterSpacing:'-0.04em', lineHeight: 0.9}}>{intV}</span>
        <span className="serif" style={{fontSize: 36, color:'var(--cc-muted)', fontStyle:'italic'}}>%</span>
      </div>
      <div style={{marginTop: 14, height: 3, background: c, width: `${intV}%`, transition:'width 700ms cubic-bezier(.2,.7,.2,1)'}}/>
    </div>
  );
}

// ── Form & H2H ─────────────────────────────────────────────────────────

function MDForm({ m }) {
  const homeForm = m.home_form?.last_5_results || []
  const awayForm = m.away_form?.last_5_results || []
  const hasForm = homeForm.length > 0 || awayForm.length > 0

  const goalsLine = formGoalsLine(m)

  const h2h = Array.isArray(m.h2h_last_5) ? m.h2h_last_5 : []
  const h2hStats = h2hAggregate(h2h)

  return (
    <section style={{maxWidth: 1080, margin:'0 auto', padding:'0 40px', display:'grid', gridTemplateColumns:'1fr 1fr', gap: 48}}>
      <div>
        <Eyebrow>Form · Last 5</Eyebrow>
        {hasForm ? (
          <>
            <div style={{marginTop: 16}}>
              <FormRow team={m.home} short={m.homeShort} crestUrl={m.homeCrest} form={homeForm}/>
              <FormRow team={m.away} short={m.awayShort} crestUrl={m.awayCrest} form={awayForm}/>
            </div>
            {goalsLine && (
              <div style={{marginTop: 24, fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 16, lineHeight: 1.5, color:'var(--cc-muted)', borderLeft:'2px solid var(--cc-gold)', paddingLeft: 16}}>
                {goalsLine}
              </div>
            )}
          </>
        ) : (
          <div style={{marginTop: 16, padding:'24px 0', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 16, lineHeight: 1.5, color:'var(--cc-muted)'}}>
            Form data not available for this fixture yet.
          </div>
        )}
      </div>
      <div>
        <Eyebrow>Head to head · Last 5 meetings</Eyebrow>
        {h2h.length > 0 ? (
          <>
            <div style={{marginTop: 16}}>
              {h2h.map((g, i) => (
                <div key={i} style={{display:'grid', gridTemplateColumns:'70px 1fr 60px 12px', gap: 14, padding:'10px 0', borderBottom:'1px solid var(--cc-line)', alignItems:'center', fontFamily:'var(--cc-mono)', fontSize: 12}}>
                  <span style={{color:'var(--cc-muted)', letterSpacing:'0.06em'}}>{formatH2HDate(g.match_date)}</span>
                  <span style={{color:'var(--cc-text)'}}>
                    {g.home_team_short_name || '—'} <span style={{color:'var(--cc-dim)'}}>vs</span> {g.away_team_short_name || '—'}
                  </span>
                  <span className="tnum serif" style={{fontStyle:'italic', fontSize: 18, fontWeight:600, color: g.result==='D' ? 'var(--cc-amber)' : 'var(--cc-text)'}}>
                    {g.home_goals != null && g.away_goals != null ? `${g.home_goals}-${g.away_goals}` : '—'}
                  </span>
                  <span style={{width: 8, height: 8, borderRadius: 2, background: g.result==='H' ? 'var(--cc-green)' : g.result==='A' ? 'var(--cc-red)' : 'var(--cc-amber)'}}/>
                </div>
              ))}
            </div>
            {h2hStats && (
              <div style={{marginTop: 12, fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.08em'}}>
                {h2hStats}
              </div>
            )}
          </>
        ) : (
          <div style={{marginTop: 16, padding:'24px 0', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 16, lineHeight: 1.5, color:'var(--cc-muted)'}}>
            No prior meetings on file.
          </div>
        )}
      </div>
    </section>
  );
}

function formGoalsLine(m) {
  const hf = m.home_form
  const af = m.away_form
  const parts = []
  if (hf && hf.goals_scored_avg_5 != null && hf.goals_conceded_avg_5 != null) {
    parts.push(`${m.homeShort} averaging ${Number(hf.goals_scored_avg_5).toFixed(1)} scored / ${Number(hf.goals_conceded_avg_5).toFixed(1)} conceded across the last 5.`)
  }
  if (af && af.goals_scored_avg_5 != null && af.goals_conceded_avg_5 != null) {
    parts.push(`${m.awayShort} ${Number(af.goals_scored_avg_5).toFixed(1)} / ${Number(af.goals_conceded_avg_5).toFixed(1)}.`)
  }
  return parts.length > 0 ? parts.join(' ') : null
}

function h2hAggregate(h2h) {
  if (!h2h || h2h.length === 0) return null
  let h = 0, d = 0, a = 0, goals = 0, withGoals = 0
  for (const g of h2h) {
    if (g.result === 'H') h++
    else if (g.result === 'A') a++
    else if (g.result === 'D') d++
    if (g.home_goals != null && g.away_goals != null) {
      goals += g.home_goals + g.away_goals
      withGoals++
    }
  }
  const avg = withGoals > 0 ? (goals / withGoals).toFixed(1) : null
  const parts = [
    `${d} DRAW${d === 1 ? '' : 'S'}`,
    `${h} HOME`,
    `${a} AWAY`,
  ]
  if (withGoals > 0) {
    parts.push(`${goals} GOALS`, `AVG ${avg}/MATCH`)
  }
  return parts.join(' · ')
}

function formatH2HDate(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10)
    return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit' })
  } catch {
    return String(iso).slice(0, 10)
  }
}

function FormRow({ team, short, crestUrl, form }) {
  return (
    <div style={{display:'flex', alignItems:'center', gap: 14, padding:'14px 0', borderBottom:'1px solid var(--cc-line)'}}>
      <Crest short={short} crestUrl={crestUrl} size={32}/>
      <div style={{flex: 1, fontFamily:'var(--cc-display)', fontSize: 16, fontWeight: 500}}>{team}</div>
      <div style={{display:'flex', gap: 6}}>
        {form.length > 0 ? form.map((r, i) => (
          <span key={i} style={{
            width: 22, height: 22, borderRadius: 4,
            display:'inline-flex', alignItems:'center', justifyContent:'center',
            fontFamily:'var(--cc-mono)', fontSize: 10, fontWeight: 600,
            background: r==='W' ? 'rgba(34,197,94,0.18)' : r==='D' ? 'rgba(251,191,36,0.18)' : 'rgba(239,68,68,0.18)',
            color: r==='W' ? 'var(--cc-green)' : r==='D' ? 'var(--cc-amber)' : 'var(--cc-red)',
            border: '1px solid currentColor',
          }}>{r}</span>
        )) : (
          <span style={{fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-dim)', letterSpacing:'0.08em'}}>NO DATA</span>
        )}
      </div>
    </div>
  );
}

// ── Why ────────────────────────────────────────────────────────────────

function MDWhy({ m }) {
  const [ref, vis] = useInView();
  const bullets = pickFor(m, 5)
  const fair = Number.isFinite(m.fairOdds) ? m.fairOdds.toFixed(2) : '—'
  const market = Number.isFinite(m.marketOdds) ? m.marketOdds.toFixed(2) : '—'
  const showEdge = m.valueCall && Number.isFinite(m.edge) && m.edge > 0
  return (
    <section ref={ref} style={{maxWidth: 1080, margin:'0 auto', padding:'0 40px'}}>
      <div style={{display:'grid', gridTemplateColumns:'200px 1fr', gap: 36, paddingTop: 28, borderTop:'1px solid var(--cc-line)'}}>
        <div>
          <Eyebrow gold>◆ The Call</Eyebrow>
          <div className="serif" style={{fontSize: 38, fontStyle:'italic', fontWeight:600, marginTop: 8, letterSpacing:'-0.02em', lineHeight: 1, color:'var(--cc-gold)'}}>{m.callTeam}</div>
          <div style={{marginTop: 12, fontFamily:'var(--cc-mono)', fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.06em', lineHeight: 1.7}}>
            CONFIDENCE&nbsp;<span className="tnum" style={{color:'var(--cc-text)'}}>{m.callConf}%</span><br/>
            FAIR&nbsp;<span className="tnum" style={{color:'var(--cc-text)'}}>{fair}</span><br/>
            BOOK&nbsp;<span className="tnum" style={{color:'var(--cc-text)'}}>{market}</span><br/>
            {showEdge && <span style={{color:'var(--cc-gold)'}}>◆ VALUE&nbsp;<span className="tnum">+{m.edge}%</span></span>}
          </div>
        </div>
        {bullets.length > 0 ? (
          <ul style={{listStyle:'none', padding:0, margin:0, display:'grid', gap: 18}}>
            {bullets.map((w, i, arr) => (
              <li key={i} style={{
                display:'grid', gridTemplateColumns:'40px 1fr', gap: 16,
                paddingBottom: 18, borderBottom: i===arr.length-1 ? 'none' : '1px solid var(--cc-line)',
                opacity: vis ? 1 : 0,
                transform: vis ? 'none' : 'translateY(12px)',
                transition: `opacity 420ms ease ${i*100}ms, transform 420ms ease ${i*100}ms`,
              }}>
                <span className="serif tnum" style={{fontSize: 32, fontStyle:'italic', fontWeight:600, color:'var(--cc-gold)', letterSpacing:'-0.04em', lineHeight: 1}}>0{i+1}</span>
                <span style={{fontFamily:'var(--cc-serif)', fontSize: 19, lineHeight: 1.4, color:'var(--cc-text)'}}>{w}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div style={{fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 18, lineHeight: 1.5, color:'var(--cc-muted)'}}>
            Reasoning library found no qualifying templates for this fixture — the model still has a call, just nothing surprising to say about it.
          </div>
        )}
      </div>
    </section>
  );
}

// ── Stats ──────────────────────────────────────────────────────────────

function MDStats({ m }) {
  const stats = [
    { k: 'Shots', h: m.home_shots, a: m.away_shots, fmt: 'n0' },
    { k: 'Shots on target', h: m.home_shots_on_target, a: m.away_shots_on_target, fmt: 'n0' },
    { k: 'Corners', h: m.home_corners, a: m.away_corners, fmt: 'n0' },
  ]
  const hasAny = stats.some((s) => s.h != null || s.a != null)
  if (!hasAny) {
    return (
      <section style={{maxWidth: 1080, margin:'0 auto', padding:'0 40px'}}>
        <div style={{padding:'24px 0', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 16, lineHeight: 1.5, color:'var(--cc-muted)', textAlign:'center', borderTop:'1px solid var(--cc-line)', borderBottom:'1px solid var(--cc-line)'}}>
          In-play stats publish after the match completes.
        </div>
      </section>
    )
  }

  const fmt = (v) => (v == null ? '—' : String(Math.round(Number(v))))
  const better = (h, a) => {
    if (h == null || a == null) return null
    if (h > a) return 'h'
    if (a > h) return 'a'
    return null
  }

  return (
    <section style={{maxWidth: 1080, margin:'0 auto', padding:'0 40px'}}>
      <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap: 0, border:'1px solid var(--cc-line)', borderRadius: 6}}>
        {stats.map((s, i) => {
          const b = better(s.h, s.a)
          const hWeight = s.h != null ? Math.max(1, Number(s.h)) : 1
          const aWeight = s.a != null ? Math.max(1, Number(s.a)) : 1
          return (
            <div key={i} style={{
              padding:'18px 20px',
              borderRight: i < stats.length - 1 ? '1px solid var(--cc-line)' : 'none',
            }}>
              <div className="cc-eyebrow">{s.k}</div>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginTop: 10}}>
                <span className="serif tnum" style={{fontSize: 24, fontStyle:'italic', fontWeight:600, color: b==='h' ? 'var(--cc-text)' : 'var(--cc-muted)'}}>{fmt(s.h)}</span>
                <span className="mono" style={{fontSize: 9, color:'var(--cc-dim)', letterSpacing:'0.1em'}}>vs</span>
                <span className="serif tnum" style={{fontSize: 24, fontStyle:'italic', fontWeight:600, color: b==='a' ? 'var(--cc-text)' : 'var(--cc-muted)'}}>{fmt(s.a)}</span>
              </div>
              <div style={{display:'flex', height: 2, marginTop: 8, background:'var(--cc-line)'}}>
                <span style={{flex: hWeight, background: b==='h' ? 'var(--cc-gold)' : 'var(--cc-line-strong)'}}/>
                <span style={{flex: aWeight, background: b==='a' ? 'var(--cc-gold)' : 'var(--cc-line-strong)'}}/>
              </div>
            </div>
          )
        })}
      </div>
      <div style={{marginTop: 12, fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-dim)', letterSpacing:'0.08em', textTransform:'uppercase'}}>
        ◆ Match-state stats only — model features (xG, possession, PPDA) aren't published.
      </div>
    </section>
  );
}

function MDFooter() {
  return (
    <footer style={{maxWidth: 1080, margin:'48px auto 0', padding:'40px 40px 0', borderTop:'1px solid var(--cc-line)', display:'flex', justifyContent:'space-between', fontFamily:'var(--cc-mono)', fontSize: 10, letterSpacing:'0.1em', color:'var(--cc-muted)', textTransform:'uppercase'}}>
      <span>← <Link to="/" style={{color:'inherit'}}>Back to Dashboard</Link></span>
      <span>Match · v26.4</span>
    </footer>
  );
}
