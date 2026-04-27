// World Cup 2026 — Direction A (editorial broadsheet)
// Masthead numerals, asymmetric grid, group cards as newspaper columns,
// knockout bracket tree. Wired to /api/v1/world-cup/* via useWorldCup().

import Aurora from '../components/cc/Aurora';
import Eyebrow from '../components/cc/Eyebrow';
import CCNav from '../components/cc/CCNav';
import UpdatedBadge from '../components/cc/UpdatedBadge';
import useCountUp from '../hooks/useCountUp';
import useCCTheme from '../hooks/useCCTheme';
import useClock from '../hooks/useClock';
import useWorldCup from '../hooks/useWorldCup';
import { emptyState } from '../lib/reasons';
import { Link } from 'react-router-dom';

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────

const MS_PER_DAY = 24 * 60 * 60 * 1000;

// Convert an ISO 3166-1 alpha-2 country code into a flag emoji using the
// regional-indicator unicode trick. Returns '' on bad input so callers can
// safely concatenate without checking.
function flagEmoji(countryCode) {
  if (!countryCode) return '';
  const cc = String(countryCode).trim().toUpperCase();
  if (cc.length !== 2 || !/^[A-Z]{2}$/.test(cc)) return '';
  const A = 0x1f1e6;
  return String.fromCodePoint(A + (cc.charCodeAt(0) - 65), A + (cc.charCodeAt(1) - 65));
}

// Inline flag pill — fixed width so layouts don't jitter when the emoji
// is missing. Renders a small bullet placeholder if the flag can't render.
function Flag({ countryCode, size = 14 }) {
  const flag = flagEmoji(countryCode);
  return (
    <span
      style={{
        display: 'inline-flex',
        width: size + 4,
        fontSize: size,
        lineHeight: 1,
        textAlign: 'center',
        flexShrink: 0,
      }}
      aria-hidden="true"
    >
      {flag || '·'}
    </span>
  );
}

function daysUntil(isoDate) {
  if (!isoDate) return null;
  const t = Date.parse(isoDate);
  if (Number.isNaN(t)) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((t - today.getTime()) / MS_PER_DAY);
}

// Standings sort: points desc, goal_diff desc, goals_for desc as final tiebreak.
function standingsOrder(teams) {
  return [...teams].sort((a, b) => {
    if (b.points !== a.points) return b.points - a.points;
    if (b.goal_diff !== a.goal_diff) return b.goal_diff - a.goal_diff;
    return (b.goals_for || 0) - (a.goals_for || 0);
  });
}

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────

export default function WorldCup() {
  const [theme, setTheme] = useCCTheme();
  const tick = useClock(5);
  const { data, loading, error } = useWorldCup();

  const overview = data?.overview;
  const groups = data?.groups || [];
  const titleOdds = data?.titleOdds || null;
  const mostLikelyChampion = data?.mostLikelyChampion || null;
  const mostLikelyFinals = data?.mostLikelyFinals || [];
  const oddsByTeamId = data?.oddsByTeamId || {};
  const contenders = titleOdds?.title_contenders || [];

  const champion = contenders[0] || null;
  const second = contenders[1] || null;
  const third = contenders[2] || null;

  const teamsTracked = groups.length
    ? groups.reduce((sum, g) => sum + (g.teams?.length || 0), 0)
    : null;
  const groupCount = groups.length || null;

  const dKickoff = daysUntil(overview?.start_date);
  const tournamentStarted = dKickoff != null && dKickoff <= 0;
  const kickoffSub = overview?.start_date
    ? `Group stage opens ${formatDate(overview.start_date)}${overview?.host_countries?.length ? ` · ${overview.host_countries.map((h) => h.name).join(' / ')}` : ''}`
    : 'Group stage opens June 13 · Mexico City';

  const simsLabel = titleOdds?.n_sims ? Number(titleOdds.n_sims).toLocaleString() : '10,000';

  const leadHeadline = buildLeadHeadline(contenders);
  const leadBody = buildLeadBody(contenders);

  return (
    <div className={`cc-root cc-${theme}`} style={{position:'relative', minHeight:'100vh', overflowX:'hidden'}}>
      <Aurora/>
      <div style={{position:'relative', zIndex: 2, padding:'40px 56px 80px'}}>
        {/* Masthead */}
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-end', paddingBottom: 14, borderBottom:'1px solid var(--cc-line-strong)'}}>
          <div className="cc-rise" style={{display:'flex', alignItems:'baseline', gap: 14}}>
            <Link to="/" style={{fontFamily:'var(--cc-serif)', fontStyle:'italic', fontWeight:700, fontSize: 30, letterSpacing:'-0.02em', color:'var(--cc-text)', textDecoration:'none'}}>CupCast</Link>
            <div className="cc-eyebrow">No. 142 · {overview?.tournament_name || 'World Cup 2026'} · {(overview?.host_countries?.map((h) => h.name).join(' · ')) || 'USA · Canada · Mexico'}</div>
          </div>
          <div style={{display:'flex', gap: 18, alignItems:'center'}}>
            <CCNav active="World Cup" theme={theme} onTheme={setTheme}/>
            <UpdatedBadge sec={tick}/>
          </div>
        </div>

        {/* Hero masthead — three monumental numerals */}
        <div className="cc-rise" style={{display:'grid', gridTemplateColumns:'1.3fr 1fr 1fr', gap: 0, borderBottom:'1px solid var(--cc-line-strong)'}}>
          {loading ? (
            <>
              <HeroSkeleton wide/>
              <HeroSkeleton/>
              <HeroSkeleton/>
            </>
          ) : titleOdds && champion ? (
            <HeroBig
              eyebrow="Predicted Champion"
              title={champion.name}
              big={Number(champion.win_tournament_pct).toFixed(1)}
              unit="%"
              sub={second
                ? `Most-likely winner across ${simsLabel} simulations · second: ${second.name} ${Number(second.win_tournament_pct).toFixed(1)}%`
                : `Most-likely winner across ${simsLabel} simulations`}
            />
          ) : (
            <HeroEmpty eyebrow="Predicted Champion" message={emptyState('calibrating')}/>
          )}

          <HeroBig
            eyebrow="Days to Kickoff"
            big={tournamentStarted
              ? (overview?.matches_played != null ? String(overview.matches_played) : 'Underway')
              : (dKickoff != null ? String(dKickoff) : '—')}
            unit=""
            sub={tournamentStarted
              ? `${overview?.current_stage || 'In progress'} · ${overview?.matches_remaining ?? 0} matches remaining`
              : kickoffSub}
          />

          <HeroBig
            eyebrow="Teams Tracked"
            big={teamsTracked != null ? String(teamsTracked) : '—'}
            unit=""
            sub={groupCount
              ? `${groupCount} groups · 32 spots in knockouts · ${overview?.matches_total ?? 104} matches`
              : '12 groups · 32 spots in knockouts · 104 matches'}
          />
        </div>

        <div style={{padding:'12px 0', display:'flex', justifyContent:'space-between', fontFamily:'var(--cc-mono)', fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.08em', textTransform:'uppercase', borderBottom:'1px solid var(--cc-line)'}}>
          <span>Tournament prob calibrated against 1958–2022 results</span>
          <span>Sims <span className="tnum" style={{color:'var(--cc-text)'}}>{simsLabel}</span></span>
          <span>Updated <span className="tnum" style={{color:'var(--cc-text)'}}>{tick}s</span> ago</span>
        </div>

        {/* Lead story — favorites pull-quote */}
        <div style={{display:'grid', gridTemplateColumns:'2fr 1fr', gap: 36, marginTop: 30, paddingBottom: 40, borderBottom:'1px solid var(--cc-line)'}}>
          <div className="cc-rise" style={{animationDelay:'120ms'}}>
            <div className="cc-eyebrow">The Field</div>
            <h2 className="serif" style={{fontSize: 64, fontStyle:'italic', fontWeight:600, letterSpacing:'-0.03em', lineHeight: 1, margin:'10px 0 12px'}}>
              {leadHeadline}
            </h2>
            <p style={{fontFamily:'var(--cc-serif)', fontSize: 20, lineHeight: 1.5, color:'var(--cc-muted)', maxWidth: 640, margin: 0}}>
              {leadBody}
            </p>
          </div>
          <aside className="cc-rise" style={{animationDelay:'200ms'}}>
            <div className="cc-eyebrow" style={{paddingBottom: 8, borderBottom:'1px solid var(--cc-line)'}}>Top 8 to win</div>
            {error ? (
              <div style={{padding:'14px 0', color:'var(--cc-muted)', fontSize: 13}}>{emptyState('error')}</div>
            ) : !titleOdds ? (
              <div style={{padding:'14px 0', color:'var(--cc-muted)', fontSize: 13}}>{emptyState('calibrating')}</div>
            ) : (
              contenders.slice(0, 8).map((c, i) => (
                <div key={c.team_id} style={{display:'grid', gridTemplateColumns:'24px 1fr 70px', gap: 10, padding:'10px 0', borderBottom:'1px solid var(--cc-line)', alignItems:'center'}}>
                  <span className="mono tnum" style={{color:'var(--cc-dim)', fontSize: 11}}>{String(i + 1).padStart(2, '0')}</span>
                  <div style={{display:'flex', alignItems:'center', gap: 10}}>
                    <Flag countryCode={c.country_code} size={16}/>
                    <span style={{fontFamily:'var(--cc-display)', fontSize: 14}}>{c.name}</span>
                  </div>
                  <span className="serif tnum" style={{fontSize: 22, fontStyle:'italic', fontWeight:600, color: i === 0 ? 'var(--cc-gold)' : 'var(--cc-text)', textAlign:'right', letterSpacing:'-0.02em'}}>
                    {Number(c.win_tournament_pct).toFixed(1)}<span style={{fontSize: 11, color:'var(--cc-muted)'}}>%</span>
                  </span>
                </div>
              ))
            )}
          </aside>
        </div>

        {/* Group cards as newspaper columns */}
        <div style={{marginTop: 40}}>
          <h2 className="serif" style={{fontSize: 36, fontStyle:'italic', fontWeight:600, letterSpacing:'-0.02em', margin:'0 0 18px'}}>The 12 groups.</h2>
          {error ? (
            <div style={{padding:'30px 0', color:'var(--cc-muted)', fontSize: 14}}>{emptyState('error')}</div>
          ) : loading ? (
            <div style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap: 0, borderTop:'1px solid var(--cc-line-strong)'}}>
              {Array.from({length: 12}).map((_, i) => (
                <GroupCardSkeleton key={i} idx={i}/>
              ))}
            </div>
          ) : groups.length ? (
            <div style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap: 0, borderTop:'1px solid var(--cc-line-strong)'}}>
              {groups.map((g, i) => (
                <GroupCard key={g.label} g={g} idx={i} oddsByTeamId={oddsByTeamId}/>
              ))}
            </div>
          ) : (
            <div style={{padding:'30px 0', color:'var(--cc-muted)', fontSize: 14}}>{emptyState('calibrating')}</div>
          )}
        </div>

        {/* Champion's path + most-likely finals — both come straight from
            the simulator output, not seed-paired. */}
        <div style={{marginTop: 60}}>
          <h2 className="serif" style={{fontSize: 36, fontStyle:'italic', fontWeight:600, letterSpacing:'-0.02em', margin:'0 0 22px'}}>The path to the trophy.</h2>
          {error ? (
            <div style={{padding:'30px 0', color:'var(--cc-muted)', fontSize: 14}}>{emptyState('error')}</div>
          ) : !titleOdds || !mostLikelyChampion?.team ? (
            <div style={{padding:'30px 0', color:'var(--cc-muted)', fontSize: 14}}>{emptyState('calibrating')}</div>
          ) : (
            <div style={{display:'grid', gridTemplateColumns:'1.5fr 1fr', gap: 56, alignItems:'start'}}>
              <ChampionPath champion={mostLikelyChampion}/>
              <MostLikelyFinals finals={mostLikelyFinals}/>
            </div>
          )}
        </div>

        <footer style={{marginTop: 48, paddingTop: 14, borderTop:'1px solid var(--cc-line-strong)', display:'flex', justifyContent:'space-between', fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.1em', textTransform:'uppercase'}}>
          <span>← <Link to="/" style={{color:'inherit'}}>Back to Dashboard</Link></span>
          <span>{overview?.model_version || 'WC26'} · {simsLabel} sim ensemble</span>
        </footer>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Hero numerals
// ──────────────────────────────────────────────────────────────────────

function HeroBig({ eyebrow, title, big, unit, sub }) {
  const numeric = parseFloat(big);
  const v = useCountUp(Number.isNaN(numeric) ? 0 : numeric, { duration: 900 });
  const display = Number.isNaN(numeric)
    ? big
    : (typeof big === 'string' && big.includes('.') ? v.toFixed(1) : Math.round(v));
  return (
    <div style={{padding:'30px 28px 30px 28px', borderRight:'1px solid var(--cc-line-strong)'}}>
      <Eyebrow>{eyebrow}</Eyebrow>
      {title && <div className="serif" style={{fontSize: 30, fontStyle:'italic', fontWeight: 600, color:'var(--cc-gold)', marginTop: 6, letterSpacing:'-0.02em'}}>{title}</div>}
      <div style={{display:'flex', alignItems:'baseline', gap: 8, marginTop: 10}}>
        <div className="serif tnum" style={{fontSize: 116, fontStyle:'italic', fontWeight: 600, letterSpacing:'-0.04em', lineHeight: 0.95}}>{display}</div>
        {unit && <div className="serif" style={{fontSize: 44, fontStyle:'italic', color:'var(--cc-muted)', fontWeight: 500}}>{unit}</div>}
      </div>
      <div style={{marginTop: 8, fontSize: 13, color:'var(--cc-muted)', lineHeight: 1.4, maxWidth: 320}}>{sub}</div>
    </div>
  );
}

function HeroSkeleton({ wide }) {
  return (
    <div style={{padding:'30px 28px 30px 28px', borderRight:'1px solid var(--cc-line-strong)'}}>
      <div style={{height: 12, width: 120, background:'var(--cc-line)', marginBottom: 18}}/>
      {wide && <div style={{height: 26, width: 180, background:'var(--cc-line)', marginBottom: 12}}/>}
      <div style={{height: 90, width: wide ? 260 : 180, background:'var(--cc-line)'}}/>
      <div style={{height: 12, width: 240, background:'var(--cc-line)', marginTop: 14}}/>
    </div>
  );
}

function HeroEmpty({ eyebrow, message }) {
  return (
    <div style={{padding:'30px 28px 30px 28px', borderRight:'1px solid var(--cc-line-strong)'}}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <div style={{marginTop: 22, fontSize: 14, color:'var(--cc-muted)', maxWidth: 320, lineHeight: 1.5}}>{message}</div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Group card
// ──────────────────────────────────────────────────────────────────────

function GroupCard({ g, idx, oddsByTeamId }) {
  const sorted = standingsOrder(g.teams || []);
  return (
    <div className="cc-rise cc-hover" style={{
      padding:'18px 18px',
      borderRight: (idx % 4 !== 3) ? '1px solid var(--cc-line)' : 'none',
      borderBottom:'1px solid var(--cc-line)',
      animationDelay: `${100 + idx * 40}ms`,
      cursor:'pointer',
    }}>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom: 12}}>
        <div className="serif" style={{fontSize: 28, fontStyle:'italic', fontWeight: 700, color:'var(--cc-gold)', letterSpacing:'-0.02em', lineHeight: 1}}>Group {g.label}</div>
        <div className="mono" style={{fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.08em'}}>QUALIFY 2/4</div>
      </div>
      {sorted.map((t, i) => {
        const odds = oddsByTeamId[t.team_id];
        const probRaw = odds?.reach_r32_pct;
        const prob = typeof probRaw === 'number' ? probRaw : null;
        const advancing = t.qualification_status === 'advancing' || i < 2;
        const eliminated = t.qualification_status === 'eliminated';
        return (
          <div key={t.team_id ?? i} style={{display:'grid', gridTemplateColumns:'14px 22px 1fr 56px', gap: 10, padding:'8px 0', borderBottom: i < sorted.length - 1 ? '1px solid var(--cc-line)' : 'none', alignItems:'center'}}>
            <span style={{
              width: 6,
              height: 6,
              borderRadius: 1,
              background: eliminated ? 'var(--cc-muted)' : (advancing ? 'var(--cc-green)' : 'var(--cc-line-strong)'),
              opacity: eliminated ? 0.5 : 1,
            }}/>
            <Flag countryCode={t.country_code} size={14}/>
            <span style={{fontFamily:'var(--cc-display)', fontSize: 13, fontWeight: 500, opacity: eliminated ? 0.5 : 1}}>{t.name}</span>
            <div style={{display:'flex', alignItems:'center', gap: 6, justifyContent:'flex-end'}}>
              <div style={{flex: 1, height: 2, background:'var(--cc-line)', maxWidth: 36}}>
                <div style={{height:'100%', width: `${prob != null ? Math.max(0, Math.min(100, prob)) : 0}%`, background: advancing ? 'var(--cc-green)' : 'var(--cc-muted)'}}/>
              </div>
              <span className="mono tnum" style={{fontSize: 11, color: advancing ? 'var(--cc-text)' : 'var(--cc-muted)'}}>
                {prob != null ? `${Math.round(prob)}%` : '—'}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function GroupCardSkeleton({ idx }) {
  return (
    <div style={{
      padding:'18px 18px',
      borderRight: (idx % 4 !== 3) ? '1px solid var(--cc-line)' : 'none',
      borderBottom:'1px solid var(--cc-line)',
    }}>
      <div style={{height: 24, width: 90, background:'var(--cc-line)', marginBottom: 14}}/>
      {Array.from({length: 4}).map((_, i) => (
        <div key={i} style={{display:'grid', gridTemplateColumns:'14px 24px 1fr 56px', gap: 10, padding:'8px 0', alignItems:'center'}}>
          <span style={{width: 6, height: 6, background:'var(--cc-line)'}}/>
          <span style={{width: 20, height: 20, background:'var(--cc-line)'}}/>
          <span style={{height: 12, background:'var(--cc-line)'}}/>
          <span style={{height: 12, background:'var(--cc-line)'}}/>
        </div>
      ))}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Champion's projected path + most-likely finals
// ──────────────────────────────────────────────────────────────────────
//
// These read the Monte Carlo output directly. `projected_path` walks the
// most-likely champion through each knockout stage with the simulator's
// actual per-matchup win probabilities and the `frequency` with which that
// matchup appeared across the 10k runs. No seed pairing — only matchups
// the simulator says are most likely to actually happen.

const STAGE_LABEL = {
  r32: 'Round of 32',
  r16: 'Round of 16',
  qf: 'Quarterfinal',
  sf: 'Semifinal',
  final: 'Final',
}

function ChampionPath({ champion }) {
  const path = champion?.projected_path || []
  const championName = champion?.team?.name || 'Champion'
  return (
    <div style={{position:'relative'}}>
      <div className="cc-eyebrow" style={{marginBottom: 14}}>{championName} · projected path</div>
      <div style={{display:'flex', flexDirection:'column', gap: 14}}>
        {path.length === 0 && (
          <div style={{padding:'18px 0', color:'var(--cc-muted)', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 16}}>
            Path data is not in the latest simulation output.
          </div>
        )}
        {path.map((step, i) => {
          const isFinal = step.stage === 'final'
          const winPct = Math.round((step.win_prob ?? 0) * 100)
          const freqPct = Math.round((step.frequency ?? 0) * 100)
          const opp = step.opponent
          return (
            <div key={i} style={{
              display:'grid',
              gridTemplateColumns:'80px 1fr auto',
              gap: 18,
              padding:'14px 16px',
              border: `1px solid ${isFinal ? 'var(--cc-gold)' : 'var(--cc-line)'}`,
              borderRadius: 6,
              background: isFinal ? 'rgba(245,158,11,0.05)' : 'transparent',
              alignItems:'center',
            }}>
              <div className="cc-eyebrow" style={{color: isFinal ? 'var(--cc-gold)' : undefined}}>
                {STAGE_LABEL[step.stage] || step.stage}
              </div>
              <div style={{display:'flex', alignItems:'center', gap: 12}}>
                <span className="mono" style={{fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.1em'}}>vs</span>
                <Flag countryCode={opp?.country_code} size={18}/>
                <span style={{fontFamily:'var(--cc-display)', fontSize: 16, fontWeight: 500, color: isFinal ? 'var(--cc-gold)' : 'var(--cc-text)'}}>
                  {opp?.name || 'TBD'}
                </span>
              </div>
              <div style={{textAlign:'right'}}>
                <div className="serif tnum" style={{fontSize: 24, fontStyle:'italic', fontWeight: 600, color: isFinal ? 'var(--cc-gold)' : 'var(--cc-text)', letterSpacing:'-0.02em', lineHeight: 1}}>
                  {winPct}<span style={{fontSize: 11, color:'var(--cc-muted)'}}>%</span>
                </div>
                <div className="mono" style={{fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.06em', marginTop: 6}}>
                  win · matchup hit in <span className="tnum" style={{color:'var(--cc-text)'}}>{freqPct}%</span> of sims
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <div style={{marginTop: 12, fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-dim)', letterSpacing:'0.08em', textTransform:'uppercase'}}>
        Frequency = how often this exact opponent is the matchup at this stage in the simulator.
      </div>
    </div>
  )
}

function MostLikelyFinals({ finals }) {
  if (!finals?.length) {
    return (
      <div style={{position:'relative'}}>
        <div className="cc-eyebrow" style={{marginBottom: 14}}>Top finals · 10k sims</div>
        <div style={{padding:'18px 0', color:'var(--cc-muted)', fontFamily:'var(--cc-serif)', fontStyle:'italic', fontSize: 14}}>
          {emptyState('calibrating')}
        </div>
      </div>
    )
  }
  const top = finals.slice(0, 6)
  const max = Math.max(...top.map((f) => f.frequency || 0))
  return (
    <div style={{position:'relative'}}>
      <div className="cc-eyebrow" style={{marginBottom: 14}}>Top finals · sim frequency</div>
      <div style={{display:'flex', flexDirection:'column', gap: 8}}>
        {top.map((f, i) => {
          const pct = (f.frequency || 0) * 100
          const widthPct = max > 0 ? Math.max(2, (f.frequency / max) * 100) : 0
          return (
            <div key={i} style={{padding:'12px 0', borderBottom: i < top.length - 1 ? '1px solid var(--cc-line)' : 'none'}}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom: 6, gap: 12}}>
                <span style={{display:'flex', alignItems:'center', gap: 8, fontFamily:'var(--cc-display)', fontSize: 14, fontWeight: 500}}>
                  <Flag countryCode={f.champion?.country_code} size={14}/>
                  <span>{f.champion?.name}</span>
                  <span style={{color:'var(--cc-muted)', fontStyle:'italic'}}>def.</span>
                  <Flag countryCode={f.runner_up?.country_code} size={14}/>
                  <span>{f.runner_up?.name}</span>
                </span>
                <span className="serif tnum" style={{fontSize: 18, fontStyle:'italic', fontWeight: 600, color: i === 0 ? 'var(--cc-gold)' : 'var(--cc-text)', letterSpacing:'-0.02em'}}>
                  {pct.toFixed(1)}<span style={{fontSize: 10, color:'var(--cc-muted)'}}>%</span>
                </span>
              </div>
              <div style={{height: 2, background:'var(--cc-line)'}}>
                <div style={{height:'100%', width: `${widthPct}%`, background: i === 0 ? 'var(--cc-gold)' : 'var(--cc-muted)', transition:'width 600ms cubic-bezier(.2,.7,.2,1)'}}/>
              </div>
            </div>
          )
        })}
      </div>
      <div style={{marginTop: 12, fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-dim)', letterSpacing:'0.08em', textTransform:'uppercase'}}>
        Each row is a champion-vs-runner-up pair that appeared in N % of sims.
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// Lead-story copy
// ──────────────────────────────────────────────────────────────────────

function buildLeadHeadline(contenders) {
  if (!contenders || contenders.length < 3) {
    return 'The field is still finding its shape.';
  }
  const top = contenders[0].win_tournament_pct;
  const third = contenders[2].win_tournament_pct;
  const gap = Math.max(0, top - third);
  if (gap < 5) return 'Three favorites, no clear winner.';
  if (gap < 10) return 'Three favorites, one tight race.';
  return 'One favorite, and a chasing pack.';
}

function buildLeadBody(contenders) {
  if (!contenders || contenders.length < 3) {
    return 'The simulation is still settling — full lead copy returns once the title-odds buckets stabilize.';
  }
  const [a, b, c] = contenders;
  const gap = Math.max(0, a.win_tournament_pct - c.win_tournament_pct);
  return `Top three sit inside a ${gap.toFixed(1)}-point band — ${a.name}, ${b.name}, ${c.name} all in striking distance.`;
}

// ──────────────────────────────────────────────────────────────────────
// Date formatting
// ──────────────────────────────────────────────────────────────────────

function formatDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric' });
}
