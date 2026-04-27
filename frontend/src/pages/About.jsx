// About — Direction A (editorial)
// Trust page. Big editorial type, the model's principles as numbered
// pull-quotes, methodology mini-charts, masthead-style team list.

import Aurora from '../components/cc/Aurora';
import Eyebrow from '../components/cc/Eyebrow';
import CCNav from '../components/cc/CCNav';
import UpdatedBadge from '../components/cc/UpdatedBadge';
import SplitWords from '../components/cc/SplitWords';
import useCCTheme from '../hooks/useCCTheme';
import useClock from '../hooks/useClock';
import { Link } from 'react-router-dom';

export default function About() {
  const [theme, setTheme] = useCCTheme();
  const tick = useClock(11);

  return (
    <div className={`cc-root cc-${theme}`} style={{position:'relative', minHeight:'100vh', overflowX:'hidden'}}>
      <Aurora/>
      <div style={{position:'relative', zIndex: 2, padding:'40px 56px 80px'}}>
        {/* Masthead */}
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-end', paddingBottom: 14, borderBottom:'2px solid var(--cc-text)'}}>
          <div className="cc-rise" style={{display:'flex', alignItems:'baseline', gap: 14}}>
            <Link to="/" style={{fontFamily:'var(--cc-serif)', fontStyle:'italic', fontWeight:700, fontSize: 30, letterSpacing:'-0.02em', color:'var(--cc-text)', textDecoration:'none'}}>CupCast</Link>
            <div className="cc-eyebrow">No. 142 · About · The Editorial Stance</div>
          </div>
          <div style={{display:'flex', gap: 18, alignItems:'center'}}>
            <CCNav active="About" theme={theme} onTheme={setTheme}/>
            <UpdatedBadge sec={tick}/>
          </div>
        </div>

        {/* Hero */}
        <section className="cc-rise" style={{padding:'60px 0 40px', borderBottom:'1px solid var(--cc-line)'}}>
          <div className="cc-eyebrow">The Stance</div>
          <h1 className="serif" style={{
            fontSize: 'clamp(56px, 9vw, 124px)',
            fontStyle:'italic', fontWeight: 600,
            letterSpacing:'-0.04em', lineHeight: 0.95,
            margin:'14px 0 0', maxWidth: 1100, textWrap:'balance',
          }}>
            <SplitWords step={50} delay={120}>We treat football fans as smart fans. Not as gamblers, not as marks, not as eyeballs.</SplitWords>
          </h1>
          <p style={{
            fontFamily:'var(--cc-serif)', fontStyle:'italic',
            fontSize: 24, lineHeight: 1.45, color:'var(--cc-muted)',
            maxWidth: 760, margin:'30px 0 0', textWrap:'pretty',
          }}>
            CupCast is a calibrated probability service for people who already understand the sport — and want a sharper, honest second opinion before kickoff and during the match. We publish what we know, what we don't, and how often we get it wrong.
          </p>
        </section>

        {/* Numerals strip */}
        <section style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', borderBottom:'1px solid var(--cc-line)'}}>
          <NumeralStrip eyebrow="Matches modelled" big="142,889" sub="2018-2026 · 7 seasons · 9 leagues"/>
          <NumeralStrip eyebrow="Season accuracy" big="64.2%" sub="+2.1% vs market baseline" gold/>
          <NumeralStrip eyebrow="Calibration error" big="0.018" sub="Brier 0.182 · log-loss 0.541"/>
          <NumeralStrip eyebrow="Years live" big="04" sub="Since the 2022 World Cup" last/>
        </section>

        {/* Principles */}
        <section style={{padding:'50px 0 30px'}}>
          <div style={{display:'grid', gridTemplateColumns:'200px 1fr', gap: 36, alignItems:'start'}}>
            <div className="cc-eyebrow" style={{paddingTop: 14, borderTop:'1px solid var(--cc-line-strong)'}}>The Principles</div>
            <ul style={{listStyle:'none', margin: 0, padding: 0, display:'grid', gap: 36}}>
              {[
                ['01','Numbers earn trust by being checkable.','Every prediction we publish is logged with a timestamp. Every claim of accuracy is recomputable from raw call history. The Model page exposes the live numbers, not a marketing screenshot from last quarter.'],
                ['02','Calibration over confidence.','A 70% pick should land 70% of the time, not 80% with a strong narrative. We measure calibration weekly and refit when buckets drift more than a percentage point — even when accuracy looks fine.'],
                ['03','Reasoning is the product, not a tooltip.','Three to five plain-English bullets per match — the same ones our analysts use to interrogate the model. If the bullets do not stand up to read-aloud, the call gets pulled.'],
                ['04','We say "we do not know" out loud.','Leagues with thin data ship as CALIBRATING, not as fake-confident numbers. The Liga MX prediction layer was dark for 14 weeks last season. Honest beats present.'],
                ['05','No betting CTAs. Ever.','We will not place a wager for you, route you to a sportsbook, or take a referral cut. Numbers are the hero — what you do with them is your business.'],
              ].map(([n, t, b], i) => (
                <li key={i} style={{display:'grid', gridTemplateColumns:'80px 1fr', gap: 24, paddingBottom: 30, borderBottom: i<4 ? '1px solid var(--cc-line)' : 'none'}}>
                  <span className="serif tnum" style={{fontSize: 64, fontStyle:'italic', fontWeight: 600, color:'var(--cc-gold)', letterSpacing:'-0.04em', lineHeight: 0.9}}>{n}</span>
                  <div>
                    <h3 className="serif" style={{margin: 0, fontSize: 32, fontStyle:'italic', fontWeight: 600, letterSpacing:'-0.02em', lineHeight: 1.1, textWrap:'balance'}}>{t}</h3>
                    <p style={{fontFamily:'var(--cc-serif)', fontSize: 17, lineHeight: 1.55, color:'var(--cc-muted)', margin:'12px 0 0', maxWidth: 720, textWrap:'pretty'}}>{b}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Methodology */}
        <section style={{padding:'40px 0 30px', borderTop:'1px solid var(--cc-line-strong)'}}>
          <div style={{display:'grid', gridTemplateColumns:'200px 1fr', gap: 36, alignItems:'start'}}>
            <div className="cc-eyebrow">The Method</div>
            <div>
              <h2 className="serif" style={{fontSize: 56, fontStyle:'italic', fontWeight: 600, letterSpacing:'-0.03em', lineHeight: 1, margin: 0, textWrap:'balance', maxWidth: 780}}>
                A small ensemble, fitted weekly, audited daily.
              </h2>
              <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap: 24, marginTop: 32}}>
                <MethodCard t="Inputs" lines={['Team xG · xGA · 38wk decay','Squad availability · injury minutes','Travel km · rest days','Venue · referee · pitch class','Weather · pressure · wind']}/>
                <MethodCard t="Models" lines={['Hierarchical Poisson · base rate','Gradient-boosted residuals','Bayesian draw inflator','Live-state RNN · 90 minute updates','Market disagreement weighting']}/>
                <MethodCard t="Audit" lines={['Calibration plot · daily','Decile drift · weekly','Per-league refit · monthly','Backtest on 1958-2022 · seasonal','Rejection log · on every miss']}/>
              </div>
            </div>
          </div>
        </section>

        {/* Masthead */}
        <section style={{padding:'40px 0 30px', borderTop:'1px solid var(--cc-line-strong)'}}>
          <div style={{display:'grid', gridTemplateColumns:'200px 1fr', gap: 36}}>
            <div className="cc-eyebrow">The Desk</div>
            <div>
              <div style={{display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap: 30}}>
                {[
                  ['Editor', 'A.M. Halász', 'Former data desk, sports broadsheet'],
                  ['Head of Models', 'P. Okafor', 'PhD stats · 11 years quant trading'],
                  ['Calibration Lead', 'I. Tanaka-Reyes', 'Forecast verification · IPCC alum'],
                  ['Live Match Editor', 'S. Brennan', 'Tactics analyst · UEFA B'],
                  ['Engineering', 'M. Lindqvist', 'Streaming data · ex-news terminal'],
                  ['Design', 'R. Vance', 'Editorial design · type history'],
                ].map(([r, n, sub], i) => (
                  <div key={i} style={{paddingBottom: 18, borderBottom:'1px solid var(--cc-line)'}}>
                    <div className="cc-eyebrow">{r}</div>
                    <div className="serif" style={{fontSize: 28, fontStyle:'italic', fontWeight: 600, marginTop: 6, letterSpacing:'-0.02em'}}>{n}</div>
                    <div style={{fontFamily:'var(--cc-serif)', fontSize: 14, color:'var(--cc-muted)', marginTop: 4}}>{sub}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Pull quote */}
        <section style={{padding:'40px 0', textAlign:'center'}}>
          <div className="serif" style={{
            fontSize: 'clamp(36px, 5vw, 60px)', fontStyle:'italic', fontWeight: 500,
            letterSpacing:'-0.02em', lineHeight: 1.15, color:'var(--cc-text)',
            maxWidth: 1100, margin:'0 auto', textWrap:'balance',
          }}>
            <span style={{color:'var(--cc-gold)'}}>"</span> If the model has nothing useful to say, it will say nothing. The hardest line we hold is the line at which a confident-looking number has not earned its confidence yet. <span style={{color:'var(--cc-gold)'}}>"</span>
          </div>
          <div style={{marginTop: 24, fontFamily:'var(--cc-mono)', fontSize: 11, color:'var(--cc-muted)', letterSpacing:'0.16em'}}>
            — A.M. HALÁSZ, EDITOR · ISSUE 001 · 2022
          </div>
        </section>

        <footer style={{marginTop: 30, paddingTop: 14, borderTop:'1px solid var(--cc-line-strong)', display:'flex', justifyContent:'space-between', fontFamily:'var(--cc-mono)', fontSize: 10, color:'var(--cc-muted)', letterSpacing:'0.1em', textTransform:'uppercase'}}>
          <span>← <Link to="/" style={{color:'inherit'}}>Back to Dashboard</Link></span>
          <span>About · Set in Fraunces, General Sans, Inter Tight, JetBrains Mono</span>
        </footer>
      </div>
    </div>
  );
}

function NumeralStrip({ eyebrow, big, sub, gold, last }) {
  return (
    <div style={{padding:'30px 28px 30px 0', borderRight: last ? 'none' : '1px solid var(--cc-line)'}}>
      <Eyebrow gold={gold}>{eyebrow}</Eyebrow>
      <div className="serif tnum" style={{fontSize: 64, fontStyle:'italic', fontWeight: 600, color: gold ? 'var(--cc-gold)' : 'var(--cc-text)', letterSpacing:'-0.04em', lineHeight: 1, marginTop: 8}}>{big}</div>
      <div style={{marginTop: 8, fontSize: 12, color:'var(--cc-muted)', lineHeight: 1.4}}>{sub}</div>
    </div>
  );
}

function MethodCard({ t, lines }) {
  return (
    <div style={{padding: 18, border:'1px solid var(--cc-line)', borderRadius: 6, background:'var(--cc-surface)'}}>
      <Eyebrow>{t}</Eyebrow>
      <ul style={{margin:'14px 0 0', padding:0, listStyle:'none', display:'grid', gap: 8}}>
        {lines.map((l, i) => (
          <li key={i} style={{display:'flex', gap: 8, fontFamily:'var(--cc-display)', fontSize: 13, color:'var(--cc-text)', lineHeight: 1.5}}>
            <span style={{color:'var(--cc-gold)', fontFamily:'var(--cc-mono)', fontSize: 9, marginTop: 4}}>◆</span>
            <span>{l}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
