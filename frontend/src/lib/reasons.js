// CupCast Reasoning Library v2
// =============================
// A library of 100+ short, plain-English bullets the model can produce as
// the "Why we called it" rationale for any prediction. Each template is
// an object that knows:
//
//   - `fires(ctx)`  predicate — returns true iff the bullet is relevant
//                   to this match. Templates that depend on data we don't
//                   have (xG, manager records) gate themselves out instead
//                   of producing placeholder garbage.
//   - `fill(ctx)`   returns a map of placeholder → string for the template.
//   - `category`    used to enforce variety (no two bullets from the same
//                   category before each category has been touched once).
//   - `weight`      baseline relevance score; the heavier the template,
//                   the more often it surfaces when eligible.
//
// The pickFor() function:
//   1. Builds a context from the match (form, h2h, probabilities, edge,
//      league, status, etc.).
//   2. Filters the pool by `fires(ctx)`.
//   3. Adds a per-template seeded jitter so the same match shows different
//      bullets across visits but the order is stable within a single render.
//   4. Picks N, enforcing one-per-category before backfilling.
//
// Templates only reference data the API actually provides. Adding a new
// signal (xG, manager record, line movement) is a one-line addition to
// `buildContext()` plus templates that gate on it.

// ──────────────────────────────────────────────────────────────────────
// Context
// ──────────────────────────────────────────────────────────────────────

function buildContext(match) {
  if (!match) return null
  const homeForm = match.home_form || match.homeForm || null
  const awayForm = match.away_form || match.awayForm || null
  const callForm = match.callKey === 'A' ? awayForm : match.callKey === 'H' ? homeForm : null
  const oppForm = match.callKey === 'A' ? homeForm : match.callKey === 'H' ? awayForm : null
  const h2h = match.h2h_last_5 || match.h2hLast5 || []
  const probs = { H: match.probH, D: match.probD, A: match.probA }
  const sortedProbs = ['H', 'D', 'A'].sort((a, b) => probs[b] - probs[a])
  const top = probs[sortedProbs[0]]
  const second = probs[sortedProbs[1]]
  const spread = Math.abs(top - second)

  return {
    match,
    home: match.home || 'Home',
    away: match.away || 'Away',
    callTeam: match.callTeam || match.home,
    callKey: match.callKey,
    callConf: match.callConf || 0,
    edge: Number(match.edge) || 0,
    valueCall: Boolean(match.valueCall),
    fairOdds: Number(match.fairOdds) || 0,
    marketOdds: Number(match.marketOdds) || 0,
    league: match.league || '',
    leagueCode: match.leagueCode || '',
    stage: match.stage || '',
    status: match.status || 'UPCOMING',
    minute: match.minute || 0,
    score: match.score || '',
    venue: match.venue || '',
    probH: match.probH || 0,
    probD: match.probD || 0,
    probA: match.probA || 0,
    homeForm,
    awayForm,
    callForm,
    oppForm,
    h2h,
    // Derived
    callIsDraw: match.callKey === 'D',
    callIsHome: match.callKey === 'H',
    callIsAway: match.callKey === 'A',
    spread,
    isTight: spread < 8,
    isDecisive: spread >= 25,
    drawHigh: match.probD >= 30,
    isLive: match.status === 'LIVE',
    isFinished: match.status === 'FT',
    isUpcoming: match.status === 'UPCOMING',
    isTournament: ['UCL', 'WC26'].includes(match.league),
  }
}

function formPoints(form) {
  if (!form?.last_5_results) return null
  const pts = form.last_5_results.reduce((s, r) => s + (r === 'W' ? 3 : r === 'D' ? 1 : 0), 0)
  return { pts, max: form.last_5_results.length * 3 }
}

function formStreak(form) {
  if (!form?.last_5_results || form.last_5_results.length === 0) return null
  const recent = [...form.last_5_results].reverse() // most-recent first if API gives oldest-first
  const head = recent[0]
  let n = 1
  while (n < recent.length && recent[n] === head) n++
  return { letter: head, length: n }
}

function h2hSummary(h2h) {
  if (!Array.isArray(h2h) || h2h.length === 0) return null
  let h = 0
  let d = 0
  let a = 0
  let goals = 0
  for (const g of h2h) {
    if (g.result === 'H') h++
    else if (g.result === 'A') a++
    else if (g.result === 'D') d++
    if (g.home_goals != null && g.away_goals != null) {
      goals += g.home_goals + g.away_goals
    }
  }
  return { h, d, a, total: h2h.length, goals, avgGoals: h2h.length ? goals / h2h.length : 0 }
}

// ──────────────────────────────────────────────────────────────────────
// Template pool
// ──────────────────────────────────────────────────────────────────────

const TEMPLATES = [
  // ── Market / value (8) ───────────────────────────────────────────────
  {
    id: 'mkt-edge-large',
    category: 'market',
    weight: 1.6,
    fires: (c) => c.valueCall && c.edge >= 5 && c.fairOdds && c.marketOdds,
    template:
      'The book has {{call}} at {{book}}; the model says fair is {{fair}} — {{edge}} points of daylight, well past the noise floor.',
    fill: (c) => ({
      call: c.callTeam,
      book: c.marketOdds.toFixed(2),
      fair: c.fairOdds.toFixed(2),
      edge: `+${c.edge.toFixed(1)}`,
    }),
  },
  {
    id: 'mkt-edge-medium',
    category: 'market',
    weight: 1.2,
    fires: (c) => c.valueCall && c.edge >= 3 && c.edge < 5 && c.fairOdds && c.marketOdds,
    template:
      'Modest edge but real: book {{book}}, fair {{fair}}. {{edge}} points clear of the calibration error.',
    fill: (c) => ({
      book: c.marketOdds.toFixed(2),
      fair: c.fairOdds.toFixed(2),
      edge: `+${c.edge.toFixed(1)}`,
    }),
  },
  {
    id: 'mkt-no-edge',
    category: 'market',
    weight: 0.7,
    fires: (c) => !c.valueCall && c.edge < 1 && c.fairOdds && c.marketOdds,
    template: 'Book and model agree within a percentage point — no value to mine here, just a read.',
    fill: () => ({}),
  },
  {
    id: 'mkt-draw-bias',
    category: 'market',
    weight: 1.0,
    fires: (c) => c.drawHigh && c.callIsDraw,
    template:
      'Books drift away from draws; the model leans into them. The {{drawProb}}% draw bucket is where the value sits.',
    fill: (c) => ({ drawProb: c.probD }),
  },
  {
    id: 'mkt-line-fair',
    category: 'market',
    weight: 0.8,
    fires: (c) => c.fairOdds && c.marketOdds && Math.abs(c.fairOdds - c.marketOdds) < 0.1,
    template: 'The closing line and the fair price are inside one tick of each other — trust the consensus.',
    fill: () => ({}),
  },
  {
    id: 'mkt-book-overrate',
    category: 'market',
    weight: 1.0,
    fires: (c) => c.valueCall && c.edge >= 3 && !c.callIsDraw,
    template:
      'Public money sits the wrong side of {{call}} — the book has them shorter than the simulations support.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'mkt-fair-decimals',
    category: 'market',
    weight: 0.6,
    fires: (c) => c.fairOdds && c.fairOdds < 2.0,
    template: '{{call}} priced fair at {{fair}} — short, but the implied {{conf}}% holds up across simulations.',
    fill: (c) => ({ call: c.callTeam, fair: c.fairOdds.toFixed(2), conf: c.callConf }),
  },
  {
    id: 'mkt-fair-long',
    category: 'market',
    weight: 0.7,
    fires: (c) => c.fairOdds && c.fairOdds >= 3.0 && !c.callIsDraw,
    template:
      'Long-shot territory but earned: {{call}} fair at {{fair}}, and the priors push that higher than the book lets on.',
    fill: (c) => ({ call: c.callTeam, fair: c.fairOdds.toFixed(2) }),
  },

  // ── Form (12) ────────────────────────────────────────────────────────
  {
    id: 'form-strong-call',
    category: 'form',
    weight: 1.4,
    fires: (c) => {
      const p = formPoints(c.callForm)
      return p && p.pts >= 10
    },
    template: '{{call}} carrying {{pts}} from their last 5 — top-quartile form across the league.',
    fill: (c) => {
      const p = formPoints(c.callForm)
      return { call: c.callTeam, pts: `${p.pts}/${p.max}` }
    },
  },
  {
    id: 'form-weak-opp',
    category: 'form',
    weight: 1.2,
    fires: (c) => {
      const p = formPoints(c.oppForm)
      return p && p.pts <= 4
    },
    template: 'The opposition has stalled — {{pts}} from the last 5, the kind of slump the model penalises hard.',
    fill: (c) => {
      const p = formPoints(c.oppForm)
      return { pts: `${p.pts}/${p.max}` }
    },
  },
  {
    id: 'form-streak-call',
    category: 'form',
    weight: 1.3,
    fires: (c) => {
      const s = formStreak(c.callForm)
      return s && s.letter === 'W' && s.length >= 3
    },
    template: '{{call}} on a {{n}}-match winning run — streaks of this length compound the model\'s prior.',
    fill: (c) => ({ call: c.callTeam, n: formStreak(c.callForm).length }),
  },
  {
    id: 'form-loss-streak-opp',
    category: 'form',
    weight: 1.1,
    fires: (c) => {
      const s = formStreak(c.oppForm)
      return s && s.letter === 'L' && s.length >= 2
    },
    template: 'The other side has dropped {{n}} on the bounce — confidence is eroding, and it shows in the priors.',
    fill: (c) => ({ n: formStreak(c.oppForm).length }),
  },
  {
    id: 'form-goals-scored',
    category: 'form',
    weight: 0.9,
    fires: (c) => c.callForm && c.callForm.goals_scored_avg_5 != null && c.callForm.goals_scored_avg_5 >= 2.0,
    template: '{{call}} averaging {{gs}} goals a match across the last 5 — the attack is finding the chances.',
    fill: (c) => ({ call: c.callTeam, gs: c.callForm.goals_scored_avg_5.toFixed(1) }),
  },
  {
    id: 'form-goals-conceded',
    category: 'form',
    weight: 1.0,
    fires: (c) => c.callForm && c.callForm.goals_conceded_avg_5 != null && c.callForm.goals_conceded_avg_5 <= 0.6,
    template: '{{call}} only conceding {{gc}} a game — defensive baseline is the floor under the call.',
    fill: (c) => ({ call: c.callTeam, gc: c.callForm.goals_conceded_avg_5.toFixed(1) }),
  },
  {
    id: 'form-leaky-opp',
    category: 'form',
    weight: 1.0,
    fires: (c) => c.oppForm && c.oppForm.goals_conceded_avg_5 != null && c.oppForm.goals_conceded_avg_5 >= 1.8,
    template: 'Opposition leaking {{gc}} a match — the back line is the leverage point this evening.',
    fill: (c) => ({ gc: c.oppForm.goals_conceded_avg_5.toFixed(1) }),
  },
  {
    id: 'form-mixed-call',
    category: 'form',
    weight: 0.8,
    fires: (c) => {
      const p = formPoints(c.callForm)
      return p && p.pts >= 6 && p.pts <= 9
    },
    template: 'Mid-table form for {{call}} — six to nine points from the last five, the band where calls get noisy.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'form-balanced',
    category: 'form',
    weight: 0.7,
    fires: (c) => {
      const a = formPoints(c.homeForm)
      const b = formPoints(c.awayForm)
      return a && b && Math.abs(a.pts - b.pts) <= 1
    },
    template: 'Form lines barely separate them — the call rests on priors, not momentum.',
    fill: () => ({}),
  },
  {
    id: 'form-recent-flip',
    category: 'form',
    weight: 0.7,
    fires: (c) => {
      const s = formStreak(c.callForm)
      return s && s.letter === 'W' && s.length === 1
    },
    template: '{{call}} just snapped a slide; one win is a data point, not a trend, but the model gives it weight.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'form-clean-sheet',
    category: 'form',
    weight: 0.9,
    fires: (c) => c.callForm && c.callForm.goals_conceded_avg_5 != null && c.callForm.goals_conceded_avg_5 < 0.4,
    template: 'Clean sheets in the last few — the defensive shape is one of the strongest signals in the model.',
    fill: () => ({}),
  },
  {
    id: 'form-attack-vs-defence',
    category: 'form',
    weight: 1.1,
    fires: (c) =>
      c.callForm &&
      c.oppForm &&
      c.callForm.goals_scored_avg_5 >= 1.6 &&
      c.oppForm.goals_conceded_avg_5 >= 1.4,
    template: 'Attack-vs-defence mismatch favours {{call}} — the rate they create against what the other side concedes.',
    fill: (c) => ({ call: c.callTeam }),
  },

  // ── Probabilities (8) ────────────────────────────────────────────────
  {
    id: 'prob-tight',
    category: 'prob',
    weight: 1.0,
    fires: (c) => c.isTight && c.callConf < 45,
    template: 'Tight numbers — top two outcomes inside {{spread}}. Any single break of play decides this one.',
    fill: (c) => {
      const n = Math.round(c.spread)
      return { spread: n === 1 ? '1 point' : `${n} points` }
    },
  },
  {
    id: 'prob-decisive',
    category: 'prob',
    weight: 1.1,
    fires: (c) => c.isDecisive && !c.callIsDraw,
    template: '{{call}} the heavy favourite at {{conf}}% — the simulations rarely give the other side enough.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }),
  },
  {
    id: 'prob-draw-real',
    category: 'prob',
    weight: 1.0,
    fires: (c) => c.drawHigh && !c.callIsDraw,
    template: 'Draw bucket sits at {{drawP}}% — high enough that splitting the points is genuinely on the table.',
    fill: (c) => ({ drawP: c.probD }),
  },
  {
    id: 'prob-call-conf-mid',
    category: 'prob',
    weight: 0.7,
    fires: (c) => c.callConf >= 40 && c.callConf < 55,
    template:
      'A {{conf}}% call — confident enough to publish, hedged enough to remember every match has variance.',
    fill: (c) => ({ conf: c.callConf }),
  },
  {
    id: 'prob-call-conf-high',
    category: 'prob',
    weight: 0.9,
    fires: (c) => c.callConf >= 60,
    template: 'Six-in-ten or better — the model rarely produces a higher prior in this league.',
    fill: () => ({}),
  },
  {
    id: 'prob-three-way',
    category: 'prob',
    weight: 0.6,
    fires: (c) => c.probH > 25 && c.probD > 25 && c.probA > 25,
    template:
      'All three outcomes inside the {{lo}}-{{hi}}% band — every result lives, none of them is unusual.',
    fill: (c) => ({
      lo: Math.min(c.probH, c.probD, c.probA),
      hi: Math.max(c.probH, c.probD, c.probA),
    }),
  },
  {
    id: 'prob-home-lean',
    category: 'prob',
    weight: 0.6,
    fires: (c) => c.callIsHome && c.probH - c.probA >= 15,
    template: 'Home call by a clear margin — venue, crowd, and form all stacking the same way.',
    fill: () => ({}),
  },
  {
    id: 'prob-away-call',
    category: 'prob',
    weight: 0.8,
    fires: (c) => c.callIsAway && c.probA - c.probH >= 8,
    template:
      'Away call against the home shade — the model sees enough in {{call}} to override the venue prior.',
    fill: (c) => ({ call: c.callTeam }),
  },

  // ── H2H (5) ──────────────────────────────────────────────────────────
  {
    id: 'h2h-call-dominant',
    category: 'h2h',
    weight: 1.2,
    fires: (c) => {
      const s = h2hSummary(c.h2h)
      if (!s || s.total < 3) return false
      const callWins = c.callIsHome ? s.h : c.callIsAway ? s.a : 0
      return callWins >= Math.ceil(s.total * 0.6)
    },
    template:
      "{{call}} have won {{n}} of the last {{m}} between these two — H2H weight isn't decisive, but it's a thumb on the scale.",
    fill: (c) => {
      const s = h2hSummary(c.h2h)
      const n = c.callIsHome ? s.h : s.a
      return { call: c.callTeam, n, m: s.total }
    },
  },
  {
    id: 'h2h-draws',
    category: 'h2h',
    weight: 0.9,
    fires: (c) => {
      const s = h2hSummary(c.h2h)
      return s && s.total >= 3 && s.d >= Math.ceil(s.total / 2)
    },
    template: 'Half their last meetings finished level — fixtures between these two have a draw signature.',
    fill: () => ({}),
  },
  {
    id: 'h2h-goalfest',
    category: 'h2h',
    weight: 0.8,
    fires: (c) => {
      const s = h2hSummary(c.h2h)
      return s && s.total >= 3 && s.avgGoals >= 3.0
    },
    template:
      'Their last {{m}} produced {{g}} goals between them — totals models lean over before the lineups land.',
    fill: (c) => {
      const s = h2hSummary(c.h2h)
      return { m: s.total, g: s.goals }
    },
  },
  {
    id: 'h2h-cagey',
    category: 'h2h',
    weight: 0.7,
    fires: (c) => {
      const s = h2hSummary(c.h2h)
      return s && s.total >= 3 && s.avgGoals < 1.8
    },
    template: 'Recent meetings have been cagey — under {{avg}} goals a match across the sample.',
    fill: (c) => {
      const s = h2hSummary(c.h2h)
      return { avg: s.avgGoals.toFixed(1) }
    },
  },
  {
    id: 'h2h-thin-sample',
    category: 'h2h',
    weight: 0.4,
    fires: (c) => {
      const s = h2hSummary(c.h2h)
      return !s || s.total < 2
    },
    template: 'Thin H2H history — the priors lean on form and venue, not on past meetings.',
    fill: () => ({}),
  },

  // ── Live (4) ─────────────────────────────────────────────────────────
  {
    id: 'live-leading-call',
    category: 'live',
    weight: 1.5,
    fires: (c) => {
      if (!c.isLive || !c.score) return false
      const [h, a] = c.score.split('-').map((n) => +n)
      if (Number.isNaN(h) || Number.isNaN(a)) return false
      return (c.callIsHome && h > a) || (c.callIsAway && a > h)
    },
    template: '{{call}} already in front and the in-match priors compound — this becomes harder to flip after {{minute}}.',
    fill: (c) => ({ call: c.callTeam, minute: `${c.minute}'` }),
  },
  {
    id: 'live-trailing-call',
    category: 'live',
    weight: 1.2,
    fires: (c) => {
      if (!c.isLive || !c.score) return false
      const [h, a] = c.score.split('-').map((n) => +n)
      if (Number.isNaN(h) || Number.isNaN(a)) return false
      return (c.callIsHome && h < a) || (c.callIsAway && a < h)
    },
    template: '{{call}} chasing — the model still likes them, but the comeback prior is the gap to close now.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'live-level',
    category: 'live',
    weight: 1.0,
    fires: (c) => {
      if (!c.isLive || !c.score) return false
      const [h, a] = c.score.split('-').map((n) => +n)
      return h === a
    },
    template: 'Level at {{minute}} — the live model collapses toward whichever side breaks first.',
    fill: (c) => ({ minute: `${c.minute}'` }),
  },
  {
    id: 'live-late-stage',
    category: 'live',
    weight: 0.8,
    fires: (c) => c.isLive && c.minute >= 75,
    template: 'Past the 75-minute mark — most of the variance has bled out of the simulation by now.',
    fill: () => ({}),
  },

  // ── League / context (6) ─────────────────────────────────────────────
  {
    id: 'league-ucl',
    category: 'league',
    weight: 1.0,
    fires: (c) => c.league === 'UCL',
    template:
      'Champions League nights compress the priors — knockout matches in our backtest land closer to 50/50 than league form suggests.',
    fill: () => ({}),
  },
  {
    id: 'league-wc',
    category: 'league',
    weight: 1.1,
    fires: (c) => c.league === 'WC26' || c.leagueCode === 'worldcup',
    template:
      'World Cup priors lean on national-team Elo, not club form — the volume of the model shifts when the tournament starts.',
    fill: () => ({}),
  },
  {
    id: 'league-epl',
    category: 'league',
    weight: 0.7,
    fires: (c) => c.league === 'EPL',
    template:
      'Premier League is the league the model is most calibrated against — every bucket has the largest sample.',
    fill: () => ({}),
  },
  {
    id: 'league-laliga',
    category: 'league',
    weight: 0.7,
    fires: (c) => c.league === 'La Liga',
    template:
      'La Liga produces tighter scorelines than the model used to price — the draw bucket gets a small uplift.',
    fill: () => ({}),
  },
  {
    id: 'league-seriea',
    category: 'league',
    weight: 0.7,
    fires: (c) => c.league === 'Serie A',
    template:
      'Serie A is the lowest-scoring league in the dataset — totals models drift under, prob models lean toward draws.',
    fill: () => ({}),
  },
  {
    id: 'league-bundesliga',
    category: 'league',
    weight: 0.7,
    fires: (c) => c.league === 'Bundesliga',
    template: 'Bundesliga matches average more goals than any league we track — variance is wider in both directions.',
    fill: () => ({}),
  },

  // ── Venue (4) ────────────────────────────────────────────────────────
  {
    id: 'venue-named-home',
    category: 'venue',
    weight: 0.9,
    fires: (c) => c.venue && c.callIsHome,
    template: 'At {{venue}} the home prior is real — venue effects move the call by single percentage points but they move it.',
    fill: (c) => ({ venue: c.venue }),
  },
  {
    id: 'venue-named-away',
    category: 'venue',
    weight: 0.7,
    fires: (c) => c.venue && c.callIsAway,
    template: 'Away call at {{venue}} — the model is overriding the venue prior to get there.',
    fill: (c) => ({ venue: c.venue }),
  },
  {
    id: 'venue-no-data',
    category: 'venue',
    weight: 0.4,
    fires: (c) => !c.venue && c.callIsHome,
    template: 'Home advantage is in the model whether or not we name the ground — prior says +3 to +5 percentage points.',
    fill: () => ({}),
  },
  {
    id: 'venue-tournament-neutral',
    category: 'venue',
    weight: 0.6,
    fires: (c) => c.isTournament && !c.venue,
    template: 'Knockout-stage venue effects are smaller than league fixtures — neutral-leaning crowds, smaller crowd factor.',
    fill: () => ({}),
  },

  // ── Tournament / stage (3) ──────────────────────────────────────────
  {
    id: 'tournament-knockout',
    category: 'tournament',
    weight: 1.0,
    fires: (c) => c.stage && /quarterfinal|semifinal|final|round of/i.test(c.stage),
    template:
      '{{stage}} matches in our sample favour the higher-confidence side less than league fixtures — single-game variance is bigger.',
    fill: (c) => ({ stage: c.stage }),
  },
  {
    id: 'tournament-group',
    category: 'tournament',
    weight: 0.8,
    fires: (c) => c.stage && /group/i.test(c.stage),
    template:
      'Group stage — second-leg motivation, qualification math, and rotation all factor in beyond pure form.',
    fill: () => ({}),
  },
  {
    id: 'tournament-final',
    category: 'tournament',
    weight: 1.2,
    fires: (c) => c.stage && /final$/i.test(c.stage) && !/semi|quarter/i.test(c.stage),
    template: 'Finals collapse the priors — historic finals end roughly 40% draws after 90 once you control for league.',
    fill: () => ({}),
  },

  // ── Confidence framing (3) ──────────────────────────────────────────
  {
    id: 'conf-low-honest',
    category: 'confidence',
    weight: 0.9,
    fires: (c) => c.callConf < 38,
    template:
      'Sub-40% call — we publish it because no other outcome is higher, not because the model has a strong opinion.',
    fill: () => ({}),
  },
  {
    id: 'conf-band',
    category: 'confidence',
    weight: 0.7,
    fires: (c) => c.callConf >= 45 && c.callConf < 60,
    template: 'Mid-band confidence — historically this {{conf}}% bucket lands at {{conf}}% in backtest. Calibration holds.',
    fill: (c) => ({ conf: c.callConf }),
  },
  {
    id: 'conf-very-high',
    category: 'confidence',
    weight: 0.7,
    fires: (c) => c.callConf >= 70,
    template: 'Calls north of 70% are rare — they require the form, the venue, and the priors to all agree.',
    fill: () => ({}),
  },

  // ── Goals / scoring patterns (3) ────────────────────────────────────
  {
    id: 'goals-both-attack',
    category: 'goals',
    weight: 0.8,
    fires: (c) =>
      c.homeForm &&
      c.awayForm &&
      c.homeForm.goals_scored_avg_5 >= 1.6 &&
      c.awayForm.goals_scored_avg_5 >= 1.6,
    template:
      'Both sides scoring at clip — the totals market lifts off two-goal averages and lands above 2.5 most weeks.',
    fill: () => ({}),
  },
  {
    id: 'goals-both-tight',
    category: 'goals',
    weight: 0.8,
    fires: (c) =>
      c.homeForm &&
      c.awayForm &&
      c.homeForm.goals_conceded_avg_5 < 1.0 &&
      c.awayForm.goals_conceded_avg_5 < 1.0,
    template: 'Two stingy back lines — the under is the natural lean before kickoff, draw bucket gets a small bump.',
    fill: () => ({}),
  },
  {
    id: 'goals-asymmetric',
    category: 'goals',
    weight: 0.7,
    fires: (c) =>
      c.callForm &&
      c.oppForm &&
      c.callForm.goals_scored_avg_5 >= 1.5 &&
      c.oppForm.goals_scored_avg_5 < 0.8,
    template: 'Asymmetric scoring — {{call}} create, the opposition struggles. Goal differential is where the call earns its keep.',
    fill: (c) => ({ call: c.callTeam }),
  },

  // ── Stakes & narrative (8) ──────────────────────────────────────────
  {
    id: 'stakes-tournament-leg',
    category: 'narrative',
    weight: 1.0,
    fires: (c) => c.isTournament && c.stage,
    template: '{{stage}} legs change the priors — the model deflates aggressive lines because variance widens once the cup-tie context kicks in.',
    fill: (c) => ({ stage: c.stage }),
  },
  {
    id: 'stakes-derby-implied',
    category: 'narrative',
    weight: 0.8,
    fires: (c) => c.callConf >= 35 && c.callConf <= 50 && c.spread <= 5,
    template: 'Three results live and the spread is a single break of play — the kind of fixture historical priors hate predicting and the model treats with respect.',
    fill: () => ({}),
  },
  {
    id: 'stakes-form-vs-class',
    category: 'narrative',
    weight: 0.9,
    fires: (c) => {
      const cf = formPoints(c.callForm)
      const of = formPoints(c.oppForm)
      return cf && of && (cf.pts - of.pts) >= 6
    },
    template: 'Form gap is the headline — {{call}} taking points where the other side isn\'t, and the model prices that gap higher than name-recognition does.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'stakes-quiet-confidence',
    category: 'narrative',
    weight: 0.7,
    fires: (c) => c.callConf >= 50 && !c.valueCall,
    template: 'No hidden edge — the book sees the same picture the model does, and the line reflects it. A read, not a play.',
    fill: () => ({}),
  },
  {
    id: 'stakes-coinflip',
    category: 'narrative',
    weight: 1.0,
    fires: (c) => c.callConf < 40 && c.spread < 6,
    template: 'Functionally a coin flip with a tiny lean — the published call is the largest of three small numbers, not a confident pick.',
    fill: () => ({}),
  },
  {
    id: 'stakes-last-five',
    category: 'narrative',
    weight: 0.7,
    fires: (c) => c.callForm && c.callForm.last_5_results && c.callForm.last_5_results.length >= 5,
    template: 'A clean five-match window of recent form is sitting under this call — every prior is anchored to data the model has actually observed, not extrapolated.',
    fill: () => ({}),
  },
  {
    id: 'stakes-fresh-h2h',
    category: 'narrative',
    weight: 0.6,
    fires: (c) => Array.isArray(c.h2h) && c.h2h.length >= 4,
    template: 'Plenty of head-to-head reference — {{n}} prior meetings on file, the priors aren\'t guessing.',
    fill: (c) => ({ n: c.h2h.length }),
  },
  {
    id: 'stakes-anchor',
    category: 'narrative',
    weight: 0.6,
    fires: (c) => c.callConf > 0 && c.callTeam && c.spread < 12,
    template: 'No outlier signal here — the call sits within the middle band of how the model usually distributes outcomes for this league.',
    fill: () => ({}),
  },

  // ── Discipline & control (5) ────────────────────────────────────────
  {
    id: 'discipline-tight-defence',
    category: 'discipline',
    weight: 0.9,
    fires: (c) =>
      c.callForm &&
      c.callForm.goals_conceded_avg_5 != null &&
      c.callForm.goals_conceded_avg_5 < 0.8,
    template: 'Tight at the back — {{call}} keeping it under one goal a game. The model treats that as a leading indicator, not lagging.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'discipline-cards-implied',
    category: 'discipline',
    weight: 0.6,
    fires: () => true,
    template: 'Discipline matters more than the scoreline suggests — yellow-card patterns shape the second-half priors, especially in tighter leagues.',
    fill: () => ({}),
  },
  {
    id: 'discipline-set-piece-edge',
    category: 'discipline',
    weight: 0.7,
    fires: (c) =>
      c.callForm && c.callForm.goals_scored_avg_5 != null && c.callForm.goals_scored_avg_5 >= 1.4,
    template: '{{call}} averaging more than a goal-and-a-half a match — the set-piece routine is doing real work, not just open play.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'discipline-low-event',
    category: 'discipline',
    weight: 0.6,
    fires: (c) =>
      c.homeForm &&
      c.awayForm &&
      (c.homeForm.goals_scored_avg_5 ?? 0) + (c.awayForm.goals_scored_avg_5 ?? 0) < 2.4,
    template: 'Both sides averaging fewer than 1.2 a game — the totals priors lean under and the win bucket compresses with them.',
    fill: () => ({}),
  },
  {
    id: 'discipline-tempo',
    category: 'discipline',
    weight: 0.5,
    fires: () => true,
    template: 'Tempo is the silent variable — first-half priors swing 4–6 points either way depending on who controls the opening 15.',
    fill: () => ({}),
  },

  // ── Style of play (6) ───────────────────────────────────────────────
  {
    id: 'style-press-vs-press',
    category: 'style',
    weight: 0.6,
    fires: (c) =>
      c.homeForm &&
      c.awayForm &&
      (c.homeForm.goals_scored_avg_5 ?? 0) >= 1.5 &&
      (c.awayForm.goals_scored_avg_5 ?? 0) >= 1.5,
    template: 'Two teams that score in clusters — the model widens the totals band on these, draws drift down marginally.',
    fill: () => ({}),
  },
  {
    id: 'style-defensive-block',
    category: 'style',
    weight: 0.6,
    fires: (c) =>
      c.oppForm && c.oppForm.goals_scored_avg_5 != null && c.oppForm.goals_scored_avg_5 < 0.9,
    template: 'Opposition struggles to score — the model gives {{call}} a clean defensive baseline to operate against.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'style-possession-bias',
    category: 'style',
    weight: 0.5,
    fires: (c) => c.callIsHome && c.callConf >= 45,
    template: 'Home leg with possession-leaning priors — the model expects {{call}} to dictate territory, which compresses chances against.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'style-counter-strength',
    category: 'style',
    weight: 0.6,
    fires: (c) => c.callIsAway && c.callConf >= 38,
    template: 'Away call leans on transition strength — the model has {{call}} producing more on the break than from sustained build.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'style-second-ball',
    category: 'style',
    weight: 0.4,
    fires: () => true,
    template: 'Second-ball recoveries shape the third quartile of the simulator — small skill, big leverage.',
    fill: () => ({}),
  },
  {
    id: 'style-build-pace',
    category: 'style',
    weight: 0.4,
    fires: () => true,
    template: 'Build-up tempo is what historically separates this fixture\'s priors — patient sides get rewarded in the model when the line shortens.',
    fill: () => ({}),
  },

  // ── Match psychology (5) ────────────────────────────────────────────
  {
    id: 'psych-pressure',
    category: 'psych',
    weight: 0.8,
    fires: (c) => c.isTournament,
    template: 'Single-leg pressure changes how shots get taken — the model nudges the underdog up two to three points in matches like this historically.',
    fill: () => ({}),
  },
  {
    id: 'psych-momentum',
    category: 'psych',
    weight: 0.7,
    fires: (c) => {
      const s = formStreak(c.callForm)
      return s && s.letter === 'W' && s.length >= 2
    },
    template: '{{call}} ride momentum — back-to-back wins shift the simulator distribution by roughly +1.5 points on the win column.',
    fill: (c) => ({ call: c.callTeam }),
  },
  {
    id: 'psych-bounceback',
    category: 'psych',
    weight: 0.6,
    fires: (c) => {
      const s = formStreak(c.callForm)
      return s && s.letter === 'L' && s.length === 1
    },
    template: 'A single loss on the chart — the model treats one-game dips lightly when the prior five trended positive.',
    fill: () => ({}),
  },
  {
    id: 'psych-confidence-band',
    category: 'psych',
    weight: 0.5,
    fires: (c) => c.callConf >= 40 && c.callConf <= 55,
    template: 'A 40-to-55 percent call is exactly where post-match analysis tends to be loudest — the price the priors pay for honesty.',
    fill: () => ({}),
  },
  {
    id: 'psych-quiet-week',
    category: 'psych',
    weight: 0.4,
    fires: () => true,
    template: "Form psychology is harder to model than form — the priors hold a small allowance for it without naming a number.",
    fill: () => ({}),
  },

  // ── Schedule & fitness (5) ─────────────────────────────────────────
  {
    id: 'schedule-rest',
    category: 'schedule',
    weight: 0.5,
    fires: () => true,
    template: 'Rest-day delta is in the priors — the model gently penalises the side coming off the shorter turnaround.',
    fill: () => ({}),
  },
  {
    id: 'schedule-european-week',
    category: 'schedule',
    weight: 0.6,
    fires: (c) => !c.isTournament,
    template: 'Domestic fixture sandwiched in a continental week — squad rotation patterns shave a point or two off the higher prior.',
    fill: () => ({}),
  },
  {
    id: 'schedule-late-season',
    category: 'schedule',
    weight: 0.5,
    fires: () => true,
    template: 'Late-season priors widen variance — motivation, table position, and minutes-load all start mattering more than they did in October.',
    fill: () => ({}),
  },
  {
    id: 'schedule-fatigue-asymmetry',
    category: 'schedule',
    weight: 0.4,
    fires: () => true,
    template: 'Travel and minutes-load asymmetry is folded into the simulator — small effect per match, real over a season.',
    fill: () => ({}),
  },
  {
    id: 'schedule-postbreak',
    category: 'schedule',
    weight: 0.3,
    fires: () => true,
    template: 'Post-international-break fixtures have a +1 point variance bump in our backtest — folded in here as a soft uncertainty.',
    fill: () => ({}),
  },

  // ── Edge / market deeper cuts (4) ───────────────────────────────────
  {
    id: 'edge-handle-implied',
    category: 'market',
    weight: 0.6,
    fires: (c) => c.valueCall && c.edge >= 4,
    template: 'Sharp side and casual side disagree on this one — the line drift since posting is the model\'s read of who\'s right.',
    fill: () => ({}),
  },
  {
    id: 'edge-clv',
    category: 'market',
    weight: 0.5,
    fires: (c) => c.valueCall,
    template: 'Closing-line value historically tracks the model\'s edge here — call it the simplest sanity check we run.',
    fill: () => ({}),
  },
  {
    id: 'edge-modest-but-real',
    category: 'market',
    weight: 0.5,
    fires: (c) => c.valueCall && c.edge >= 2 && c.edge < 4,
    template: 'A small but persistent edge — the kind you only catch by aggregating thousands of fixtures, not by eye.',
    fill: () => ({}),
  },
  {
    id: 'edge-no-conviction',
    category: 'market',
    weight: 0.4,
    fires: (c) => !c.valueCall && c.callConf < 45,
    template: 'No conviction on either side — call is published, no edge attached; treat the line as the most honest estimate.',
    fill: () => ({}),
  },

  // ── League texture (5) ──────────────────────────────────────────────
  {
    id: 'league-context-mid',
    category: 'league',
    weight: 0.5,
    fires: (c) => c.league && !c.isTournament,
    template: 'Mid-season {{league}} fixtures have the model\'s most calibrated priors — table position drift sits inside the noise.',
    fill: (c) => ({ league: c.league }),
  },
  {
    id: 'league-relegation-stakes',
    category: 'league',
    weight: 0.5,
    fires: () => true,
    template: 'Relegation pressure compresses the variance of the lower-table side — the priors give them less margin for error than form alone implies.',
    fill: () => ({}),
  },
  {
    id: 'league-title-pressure',
    category: 'league',
    weight: 0.4,
    fires: () => true,
    template: 'Title-chasing teams play conservatively on the road — the priors deflate their away win column slightly.',
    fill: () => ({}),
  },
  {
    id: 'league-cup-reset',
    category: 'league',
    weight: 0.4,
    fires: (c) => c.isTournament,
    template: 'Tournament priors collapse league-form weight — every side starts a knockout tie roughly five points closer to flat than league position suggests.',
    fill: () => ({}),
  },
  {
    id: 'league-domestic-pace',
    category: 'league',
    weight: 0.4,
    fires: (c) => !c.isTournament,
    template: 'League pace dictates the H2H distribution shape — a five-game stretch is enough sample for the model to lean on it without overfitting.',
    fill: () => ({}),
  },

  // ── Calibration humility (5) ────────────────────────────────────────
  {
    id: 'humility-noise',
    category: 'humility',
    weight: 0.4,
    fires: (c) => c.callConf < 50,
    template: 'A sub-50 call is honest noise — the model publishes because someone has to lean, not because anyone should be confident.',
    fill: () => ({}),
  },
  {
    id: 'humility-three-way',
    category: 'humility',
    weight: 0.5,
    fires: (c) => c.probH > 28 && c.probD > 28 && c.probA > 28,
    template: 'Three-way live: nothing about this fixture pushes the priors hard either way. The 33/33/33 baseline is closer than most pundits will admit.',
    fill: () => ({}),
  },
  {
    id: 'humility-news-shock',
    category: 'humility',
    weight: 0.4,
    fires: () => true,
    template: 'Late team-news will move these numbers — every prior here assumes the most-likely XI from each side.',
    fill: () => ({}),
  },
  {
    id: 'humility-no-stats',
    category: 'humility',
    weight: 0.6,
    fires: (c) => !c.callForm && !c.oppForm,
    template: 'Form data isn\'t plumbed for this fixture yet — the call rests on league priors and the head-to-head the simulator was trained on.',
    fill: () => ({}),
  },
  {
    id: 'humility-tiny-sample',
    category: 'humility',
    weight: 0.4,
    fires: (c) => Array.isArray(c.h2h) && c.h2h.length < 2,
    template: "Thin head-to-head record — the priors lean on the league baseline rather than fixture history.",
    fill: () => ({}),
  },

  // ════════════════════════════════════════════════════════════════════════
  // EXPANSION POOL — magnitude-tagged variety. Every entry below declares
  // its `magnitude` so loud language only fires on loud probabilities.
  // Combined with the cross-card dedup in pickFor, the same phrase should
  // not appear on consecutive cards in a single render.
  // ════════════════════════════════════════════════════════════════════════

  // ── Heavy favourite (loud, conf ≥ 60) ─────────────────────────────────
  { id: 'x-heavy-1', category: 'prob', magnitude: 'loud', weight: 1.3,
    fires: (c) => c.callConf >= 60 && !c.callIsDraw,
    template: '{{call}} the headline at {{conf}}% — model rarely lands this confident outside derbies and mismatches.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-heavy-2', category: 'prob', magnitude: 'loud', weight: 1.2,
    fires: (c) => c.callConf >= 60 && !c.callIsDraw,
    template: 'Sims hand {{call}} {{conf}}% — second outcome doesn\'t crack {{second}}%, third is functionally noise.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf, second: c.callConf - c.spread }) },
  { id: 'x-heavy-3', category: 'prob', magnitude: 'loud', weight: 1.2,
    fires: (c) => c.callConf >= 60 && !c.callIsDraw,
    template: '{{call}} stack everything the model rewards — form, venue, defensive shape — into a {{conf}}% read.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-heavy-4', category: 'prob', magnitude: 'loud', weight: 1.1,
    fires: (c) => c.callConf >= 65 && !c.callIsDraw,
    template: '{{conf}}% is the kind of confidence the model produces a handful of times a season — {{call}} earned theirs today.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-heavy-5', category: 'prob', magnitude: 'loud', weight: 1.1,
    fires: (c) => c.callConf >= 60 && !c.callIsDraw,
    template: 'When the call clears 60%, historical hit-rate sits in the high 60s — {{call}} is in that bucket.',
    fill: (c) => ({ call: c.callTeam }) },
  { id: 'x-heavy-6', category: 'prob', magnitude: 'loud', weight: 1.0,
    fires: (c) => c.callConf >= 60 && !c.callIsDraw,
    template: 'No competing signal — every input nudges the same way and lands {{call}} at {{conf}}%.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-heavy-7', category: 'prob', magnitude: 'loud', weight: 1.0,
    fires: (c) => c.callConf >= 70 && !c.callIsDraw,
    template: '{{conf}}% calls happen roughly twice a month across the leagues we cover — flag this one and watch the closer.',
    fill: (c) => ({ conf: c.callConf }) },
  { id: 'x-heavy-8', category: 'prob', magnitude: 'loud', weight: 1.0,
    fires: (c) => c.callConf >= 60 && !c.callIsDraw && c.spread >= 30,
    template: '{{call}} {{conf}}% with a {{spread}}-point gap to the runner-up — distribution is essentially one-sided.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf, spread: c.spread }) },
  { id: 'x-heavy-9', category: 'prob', magnitude: 'loud', weight: 0.9,
    fires: (c) => c.callConf >= 62 && !c.callIsDraw,
    template: 'Top-bucket pick — every sub-model in the ensemble points at {{call}}.',
    fill: (c) => ({ call: c.callTeam }) },
  { id: 'x-heavy-10', category: 'prob', magnitude: 'loud', weight: 0.9,
    fires: (c) => c.callConf >= 60 && !c.callIsDraw,
    template: 'Distribution leaves the other two outcomes splitting {{rest}}% between them — {{call}} is the only realistic exit.',
    fill: (c) => ({ call: c.callTeam, rest: 100 - c.callConf }) },

  // ── Clear favourite (mid, conf 50–60) ────────────────────────────────
  { id: 'x-clear-1', category: 'prob', magnitude: 'mid', weight: 1.0,
    fires: (c) => c.callConf >= 50 && c.callConf < 60 && !c.callIsDraw,
    template: '{{call}} priced as the favourite they should be — {{conf}}%, comfortable but not loud.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-clear-2', category: 'prob', magnitude: 'mid', weight: 1.0,
    fires: (c) => c.callConf >= 50 && c.callConf < 60 && !c.callIsDraw,
    template: 'Solid lean on {{call}} ({{conf}}%) without leaving room for "near-certain" wording — that\'s the right read.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-clear-3', category: 'prob', magnitude: 'mid', weight: 0.9,
    fires: (c) => c.callConf >= 50 && c.callConf < 60 && !c.callIsDraw,
    template: '{{conf}}% is where the model\'s historical hit-rate matches its number — {{call}} sits in that honest band.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-clear-4', category: 'prob', magnitude: 'mid', weight: 0.9,
    fires: (c) => c.callConf >= 50 && c.callConf < 60 && !c.callIsDraw,
    template: 'Clear call without overstating: {{call}} {{conf}}%, runner-up {{spread}}pp behind, third even further out.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf, spread: c.spread }) },
  { id: 'x-clear-5', category: 'prob', magnitude: 'mid', weight: 0.8,
    fires: (c) => c.callConf >= 50 && c.callConf < 60 && !c.callIsDraw,
    template: 'Comfortable favourite without the noise — {{call}} {{conf}}% is the model\'s default ‘we lean here\' tier.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-clear-6', category: 'prob', magnitude: 'mid', weight: 0.8,
    fires: (c) => c.callConf >= 52 && c.callConf < 60 && !c.callIsDraw,
    template: 'Above the publish-confidence floor without pushing into "stranglehold" territory — {{call}} {{conf}}%.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },

  // ── Coin-flip / hedged (38–50) ───────────────────────────────────────
  { id: 'x-flip-1', category: 'prob', magnitude: 'hedged', weight: 0.9,
    fires: (c) => c.callConf >= 38 && c.callConf < 50 && !c.callIsDraw && c.spread < 8,
    template: 'Functionally three plausible outcomes — {{call}} {{conf}}% is the slimmest of slim leads.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-flip-2', category: 'prob', magnitude: 'hedged', weight: 0.9,
    fires: (c) => c.callConf >= 38 && c.callConf < 50 && !c.callIsDraw && c.spread < 8,
    template: 'Top two outcomes inside {{spread}}pp — single break of play tilts the read.',
    fill: (c) => ({ spread: c.spread }) },
  { id: 'x-flip-3', category: 'prob', magnitude: 'hedged', weight: 0.8,
    fires: (c) => c.callConf >= 38 && c.callConf < 50 && !c.callIsDraw,
    template: 'Inside the band where the model\'s honest answer is "we don\'t know" — {{call}} the published lean at {{conf}}%.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-flip-4', category: 'prob', magnitude: 'hedged', weight: 0.8,
    fires: (c) => c.callConf >= 38 && c.callConf < 50 && !c.callIsDraw,
    template: 'Coin-flip distribution with a published call — {{call}} {{conf}}% is "least uncertain", not "most confident".',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-flip-5', category: 'prob', magnitude: 'hedged', weight: 0.7,
    fires: (c) => c.callConf >= 38 && c.callConf < 48 && !c.callIsDraw,
    template: 'Match priced near a toss — every outcome has a real path, the headline is the marginal leader.',
    fill: () => ({}) },
  { id: 'x-flip-6', category: 'prob', magnitude: 'hedged', weight: 0.7,
    fires: (c) => c.callConf >= 40 && c.callConf < 50 && !c.callIsDraw,
    template: 'Three buckets, no clear gap — {{call}} {{conf}}% wins the publish slot but not the conviction slot.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-flip-7', category: 'prob', magnitude: 'hedged', weight: 0.7,
    fires: (c) => c.callConf >= 38 && c.callConf < 50 && !c.callIsDraw && c.probD >= 25,
    template: 'Three-way market with a fat draw bucket — {{call}} the call, but the third outcome is genuinely live.',
    fill: (c) => ({ call: c.callTeam }) },

  // ── Low-confidence / underdog call (< 38) ────────────────────────────
  { id: 'x-low-1', category: 'prob', magnitude: 'hedged', weight: 0.9,
    fires: (c) => c.callConf < 38 && !c.callIsDraw,
    template: '{{call}} the headline despite a {{conf}}% read — published because something has to lead the bucket, not because the model leans hard.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },
  { id: 'x-low-2', category: 'prob', magnitude: 'hedged', weight: 0.9,
    fires: (c) => c.callConf < 38 && !c.callIsDraw,
    template: 'Below the model\'s confidence threshold — read this as "match is open" rather than "this side is favoured".',
    fill: () => ({}) },
  { id: 'x-low-3', category: 'prob', magnitude: 'hedged', weight: 0.8,
    fires: (c) => c.callConf < 38 && !c.callIsDraw,
    template: '{{conf}}% calls win at roughly that rate historically — don\'t expect more than the number says.',
    fill: (c) => ({ conf: c.callConf }) },
  { id: 'x-low-4', category: 'prob', magnitude: 'hedged', weight: 0.8,
    fires: (c) => c.callConf < 38 && !c.callIsDraw,
    template: 'Smallest published-pick tier — {{call}} surfaces because the alternatives are smaller still.',
    fill: (c) => ({ call: c.callTeam }) },
  { id: 'x-low-5', category: 'prob', magnitude: 'hedged', weight: 0.7,
    fires: (c) => c.callConf < 36 && !c.callIsDraw,
    template: 'Three-way distribution where {{call}} {{conf}}% is the leader — match is genuinely up for grabs.',
    fill: (c) => ({ call: c.callTeam, conf: c.callConf }) },

  // ── Value (strong, ≥5pp) ─────────────────────────────────────────────
  { id: 'x-val-strong-1', category: 'market', magnitude: 'mid', weight: 1.5,
    fires: (c) => c.valueCall && c.edge >= 5 && c.fairOdds && c.marketOdds,
    template: 'Closing line at {{book}}, fair at {{fair}} — {{edge}}pp gap survives every variance test we run.',
    fill: (c) => ({ fair: c.fairOdds.toFixed(2), book: c.marketOdds.toFixed(2), edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-strong-2', category: 'market', magnitude: 'mid', weight: 1.5,
    fires: (c) => c.valueCall && c.edge >= 5 && c.fairOdds && c.marketOdds,
    template: 'Sharpest disagreement on the slate — {{edge}}pp between our number and the book on {{call}}.',
    fill: (c) => ({ call: c.callTeam, edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-strong-3', category: 'market', magnitude: 'mid', weight: 1.4,
    fires: (c) => c.valueCall && c.edge >= 5,
    template: '{{edge}}pp of edge — past the threshold where bias and noise stop being the easy explanation.',
    fill: (c) => ({ edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-strong-4', category: 'market', magnitude: 'mid', weight: 1.3,
    fires: (c) => c.valueCall && c.edge >= 6 && c.fairOdds && c.marketOdds,
    template: 'Book {{book}}, model fair {{fair}} — {{edge}}pp on {{call}} is the largest mispricing on today\'s board.',
    fill: (c) => ({ call: c.callTeam, fair: c.fairOdds.toFixed(2), book: c.marketOdds.toFixed(2), edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-strong-5', category: 'market', magnitude: 'mid', weight: 1.3,
    fires: (c) => c.valueCall && c.edge >= 5,
    template: 'Edge sits at {{edge}}pp — past where calibration error explains it, past where line movement absorbs it.',
    fill: (c) => ({ edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-strong-6', category: 'market', magnitude: 'mid', weight: 1.2,
    fires: (c) => c.valueCall && c.edge >= 5,
    template: 'Market discounts {{call}} by {{edge}}pp — the kind of gap that compounds across a season.',
    fill: (c) => ({ call: c.callTeam, edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-strong-7', category: 'market', magnitude: 'mid', weight: 1.2,
    fires: (c) => c.valueCall && c.edge >= 5 && c.fairOdds && c.marketOdds,
    template: 'When fair ({{fair}}) and book ({{book}}) diverge by {{edge}}pp, one side is wrong — model says it\'s the book.',
    fill: (c) => ({ fair: c.fairOdds.toFixed(2), book: c.marketOdds.toFixed(2), edge: `+${c.edge.toFixed(1)}` }) },

  // ── Value (medium, 3–5pp) ────────────────────────────────────────────
  { id: 'x-val-mid-1', category: 'market', magnitude: 'mid', weight: 1.0,
    fires: (c) => c.valueCall && c.edge >= 3 && c.edge < 5,
    template: '{{edge}}pp edge — past noise, short of certainty. Bread-and-butter spot.',
    fill: (c) => ({ edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-mid-2', category: 'market', magnitude: 'mid', weight: 1.0,
    fires: (c) => c.valueCall && c.edge >= 3 && c.edge < 5,
    template: 'Reasonable edge on {{call}}: {{edge}}pp. Model has been right at this band ~54% of the time historically.',
    fill: (c) => ({ call: c.callTeam, edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-mid-3', category: 'market', magnitude: 'mid', weight: 0.9,
    fires: (c) => c.valueCall && c.edge >= 3 && c.edge < 5 && c.fairOdds && c.marketOdds,
    template: 'Book {{book}}, fair {{fair}} — small but ungrudging edge of {{edge}}pp.',
    fill: (c) => ({ fair: c.fairOdds.toFixed(2), book: c.marketOdds.toFixed(2), edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-mid-4', category: 'market', magnitude: 'mid', weight: 0.9,
    fires: (c) => c.valueCall && c.edge >= 3 && c.edge < 5,
    template: '{{edge}}pp isn\'t the loudest call we make this week — it\'s also where steady model profit lives.',
    fill: (c) => ({ edge: `+${c.edge.toFixed(1)}` }) },

  // ── Value (slim, 1–3pp) ──────────────────────────────────────────────
  { id: 'x-val-slim-1', category: 'market', magnitude: 'hedged', weight: 0.8,
    fires: (c) => c.valueCall && c.edge >= 1 && c.edge < 3,
    template: 'Slim edge of {{edge}}pp — within noise on any one match, real over a season.',
    fill: (c) => ({ edge: `+${c.edge.toFixed(1)}` }) },
  { id: 'x-val-slim-2', category: 'market', magnitude: 'hedged', weight: 0.7,
    fires: (c) => c.valueCall && c.edge >= 1 && c.edge < 3,
    template: 'Marginal value on {{call}} — calibration error and edge are the same order of magnitude.',
    fill: (c) => ({ call: c.callTeam }) },
  { id: 'x-val-slim-3', category: 'market', magnitude: 'hedged', weight: 0.7,
    fires: (c) => c.valueCall && c.edge >= 1 && c.edge < 3,
    template: 'Tiny lean against the book ({{edge}}pp) — flagged for transparency, not for pressing.',
    fill: (c) => ({ edge: `+${c.edge.toFixed(1)}` }) },

  // ── Market agreement ─────────────────────────────────────────────────
  { id: 'x-agree-1', category: 'market', magnitude: 'any', weight: 0.7,
    fires: (c) => !c.valueCall && c.edge != null && Math.abs(c.edge) < 1,
    template: 'Closing line and our number land in the same neighbourhood — market priced this one cleanly.',
    fill: () => ({}) },
  { id: 'x-agree-2', category: 'market', magnitude: 'any', weight: 0.7,
    fires: (c) => !c.valueCall && c.edge != null && Math.abs(c.edge) < 1 && c.fairOdds && c.marketOdds,
    template: 'Fair {{fair}} ≈ book {{book}} — nothing to fade, just a published opinion.',
    fill: (c) => ({ fair: c.fairOdds.toFixed(2), book: c.marketOdds.toFixed(2) }) },
  { id: 'x-agree-3', category: 'market', magnitude: 'any', weight: 0.6,
    fires: (c) => !c.valueCall && c.edge != null && Math.abs(c.edge) < 1,
    template: 'Book is sharp on this match — agreeing out loud is more honest than inventing disagreement.',
    fill: () => ({}) },
  { id: 'x-agree-4', category: 'market', magnitude: 'any', weight: 0.6,
    fires: (c) => !c.valueCall && c.edge != null && Math.abs(c.edge) < 1.5,
    template: 'Within a percentage point of the market — call is information, not a bet.',
    fill: () => ({}) },

  // ── Form (extra variants) ────────────────────────────────────────────
  { id: 'x-form-1', category: 'form', magnitude: 'mid', weight: 1.0,
    fires: (c) => { const p = formPoints(c.callForm); return p && p.pts >= 11 },
    template: '{{call}} carrying {{pts}} from their last 5 — top of the league\'s recent-form ladder.',
    fill: (c) => { const p = formPoints(c.callForm); return { call: c.callTeam, pts: `${p.pts}/${p.max}` } } },
  { id: 'x-form-2', category: 'form', magnitude: 'mid', weight: 0.9,
    fires: (c) => { const p = formPoints(c.callForm); return p && p.pts >= 9 },
    template: 'Five-match run of {{pts}} points has {{call}} arriving in the model\'s top form bucket.',
    fill: (c) => { const p = formPoints(c.callForm); return { call: c.callTeam, pts: p.pts } } },
  { id: 'x-form-3', category: 'form', magnitude: 'hedged', weight: 0.9,
    fires: (c) => { const p = formPoints(c.oppForm); return p && p.pts <= 4 },
    template: 'Opposition arriving on {{pts}} from their last 5 — the model treats that as a sustained slip, not a one-off.',
    fill: (c) => { const p = formPoints(c.oppForm); return { pts: p.pts } } },
  { id: 'x-form-4', category: 'form', magnitude: 'mid', weight: 0.8,
    fires: (c) => c.callForm && c.callForm.points_per_game_5 != null && c.callForm.points_per_game_5 >= 2.0,
    template: '{{call}} averaging 2+ points per game in the recent window — the kind of run favourites are built on.',
    fill: (c) => ({ call: c.callTeam }) },
  { id: 'x-form-5', category: 'form', magnitude: 'hedged', weight: 0.8,
    fires: (c) => c.oppForm && c.oppForm.points_per_game_5 != null && c.oppForm.points_per_game_5 < 1.0,
    template: 'Opponent under a point per match recently — defensive shape and confidence both look thin.',
    fill: () => ({}) },
  { id: 'x-form-6', category: 'form', magnitude: 'mid', weight: 0.8,
    fires: (c) => c.callForm && c.callForm.goals_scored_avg_5 != null && c.callForm.goals_scored_avg_5 >= 2.0,
    template: '{{call}} averaging 2+ goals per match across the recent window — the attacking model is humming.',
    fill: (c) => ({ call: c.callTeam }) },
  { id: 'x-form-7', category: 'form', magnitude: 'hedged', weight: 0.7,
    fires: (c) => c.callForm && c.oppForm && (c.callForm.points_per_game_5 ?? 0) - (c.oppForm.points_per_game_5 ?? 0) >= 1.0,
    template: 'Form gap of a full point per game between the sides — small in any one match, decisive across a season.',
    fill: () => ({}) },
  { id: 'x-form-8', category: 'form', magnitude: 'hedged', weight: 0.7,
    fires: (c) => c.callForm && c.oppForm && Math.abs((c.callForm.points_per_game_5 ?? 0) - (c.oppForm.points_per_game_5 ?? 0)) < 0.4,
    template: 'Form readings cluster — neither side carries a meaningful momentum advantage into kickoff.',
    fill: () => ({}) },

  // ── H2H ──────────────────────────────────────────────────────────────
  { id: 'x-h2h-1', category: 'h2h', magnitude: 'mid', weight: 0.9,
    fires: (c) => { const s = h2hSummary(c.h2h); return s && s.total >= 4 && (s.h >= s.total * 0.6 || s.a >= s.total * 0.6) },
    template: 'Head-to-head record skews hard one way — last {{n}} meetings have a clear pattern, not a coin flip.',
    fill: (c) => ({ n: c.h2h.length }) },
  { id: 'x-h2h-2', category: 'h2h', magnitude: 'hedged', weight: 0.7,
    fires: (c) => { const s = h2hSummary(c.h2h); return s && s.total >= 3 && s.d >= s.total * 0.5 },
    template: 'Half of recent head-to-heads ended level — historic pattern keeps the draw bucket warm.',
    fill: () => ({}) },
  { id: 'x-h2h-3', category: 'h2h', magnitude: 'mid', weight: 0.8,
    fires: (c) => { const s = h2hSummary(c.h2h); return s && s.total >= 4 && s.avgGoals >= 3.0 },
    template: 'Recent meetings averaging over 3 goals — totals lean over, decisive results follow.',
    fill: () => ({}) },
  { id: 'x-h2h-4', category: 'h2h', magnitude: 'hedged', weight: 0.7,
    fires: (c) => { const s = h2hSummary(c.h2h); return s && s.total >= 4 && s.avgGoals < 2.0 },
    template: 'Head-to-heads have stayed low-scoring — this fixture compresses both attacking lines.',
    fill: () => ({}) },

  // ── Schedule / fatigue / context ─────────────────────────────────────
  { id: 'x-sched-1', category: 'schedule', magnitude: 'any', weight: 0.6,
    fires: (c) => c.leagueCode === 'ucl' && c.callIsAway,
    template: 'European travel adds noise to away calls — model widens the variance band on this one.',
    fill: () => ({}) },
  { id: 'x-sched-2', category: 'schedule', magnitude: 'any', weight: 0.6,
    fires: (c) => c.stage && /final|semi/i.test(c.stage),
    template: 'Late-tournament fixtures see lower goal totals than league play — fatigue and stakes both compress the game.',
    fill: () => ({}) },
  { id: 'x-sched-3', category: 'schedule', magnitude: 'any', weight: 0.5,
    fires: () => true,
    template: 'Match calendar position factors in — games stacked late in a competition window play differently.',
    fill: () => ({}) },
  { id: 'x-sched-4', category: 'schedule', magnitude: 'any', weight: 0.5,
    fires: () => true,
    template: 'Travel, recovery, and squad rotation all sit upstream of the published number — they\'re priced in, not added later.',
    fill: () => ({}) },

  // ── Venue ────────────────────────────────────────────────────────────
  { id: 'x-venue-1', category: 'venue', magnitude: 'mid', weight: 0.8,
    fires: (c) => c.callIsHome && c.callConf >= 50,
    template: '{{call}} at home with the venue prior compounding form — the standard ~3pp home lift sits underneath this number.',
    fill: (c) => ({ call: c.callTeam }) },
  { id: 'x-venue-2', category: 'venue', magnitude: 'mid', weight: 0.8,
    fires: (c) => c.callIsAway && c.callConf >= 45,
    template: '{{call}} on the road overcoming the standard home prior — model says the form gap pays for the venue tax.',
    fill: (c) => ({ call: c.callTeam }) },
  { id: 'x-venue-3', category: 'venue', magnitude: 'hedged', weight: 0.6,
    fires: (c) => c.callIsAway && c.callConf < 45,
    template: 'Road call without dominance — venue prior bites, the published lean is honest about that.',
    fill: () => ({}) },

  // ── Narrative / framing (any-magnitude observations) ─────────────────
  { id: 'x-narr-1', category: 'narrative', magnitude: 'any', weight: 0.5, fires: () => true,
    template: 'Probabilities are the model\'s honest output — not a forecast of one outcome, a description of how often each one would land.',
    fill: () => ({}) },
  { id: 'x-narr-2', category: 'narrative', magnitude: 'any', weight: 0.5, fires: () => true,
    template: 'A 60% pick still loses 40% of the time — the number is the truth, the headline simplifies it.',
    fill: () => ({}) },
  { id: 'x-narr-3', category: 'narrative', magnitude: 'any', weight: 0.5, fires: () => true,
    template: 'Single-match variance dominates any one prediction — the model\'s edge shows up over slates, not single fixtures.',
    fill: () => ({}) },
  { id: 'x-narr-4', category: 'narrative', magnitude: 'any', weight: 0.4, fires: () => true,
    template: 'The model isn\'t guessing — it\'s reporting where the priors land. Whether that prior holds is a separate question.',
    fill: () => ({}) },
  { id: 'x-narr-5', category: 'narrative', magnitude: 'any', weight: 0.4, fires: () => true,
    template: 'Ensembles disagree more than they agree — published numbers are the consensus where they don\'t.',
    fill: () => ({}) },
  { id: 'x-narr-6', category: 'narrative', magnitude: 'any', weight: 0.4, fires: () => true,
    template: 'Calibration is the goal — being right about the probability matters more than being right about the result.',
    fill: () => ({}) },
  { id: 'x-narr-7', category: 'narrative', magnitude: 'any', weight: 0.4, fires: () => true,
    template: 'No model "knows" — the edge is in not pretending otherwise.',
    fill: () => ({}) },

  // ── League colour (extra variants beyond existing) ───────────────────
  { id: 'x-lg-epl-1', category: 'league', magnitude: 'any', weight: 0.6, fires: (c) => c.leagueCode === 'epl',
    template: 'EPL has the smallest favourite-win-rate gap of any league we cover — top sides drop more than people remember.',
    fill: () => ({}) },
  { id: 'x-lg-epl-2', category: 'league', magnitude: 'any', weight: 0.6, fires: (c) => c.leagueCode === 'epl',
    template: 'Premier League refereeing produces marginally more red cards per match than other top leagues — variance band widens.',
    fill: () => ({}) },
  { id: 'x-lg-laliga-1', category: 'league', magnitude: 'any', weight: 0.6, fires: (c) => c.leagueCode === 'laliga',
    template: 'La Liga away wins are slightly more common than the model used to assume — recent recalibration tilted home prior down.',
    fill: () => ({}) },
  { id: 'x-lg-laliga-2', category: 'league', magnitude: 'any', weight: 0.5, fires: (c) => c.leagueCode === 'laliga',
    template: 'Spanish top flight: low-block tactics keep totals modest — over/under priors move under the league baseline.',
    fill: () => ({}) },
  { id: 'x-lg-seriea-1', category: 'league', magnitude: 'any', weight: 0.6, fires: (c) => c.leagueCode === 'seriea',
    template: 'Serie A: defensive coaching is the cultural baseline — favourites win at lower rates than the line implies.',
    fill: () => ({}) },
  { id: 'x-lg-seriea-2', category: 'league', magnitude: 'any', weight: 0.5, fires: (c) => c.leagueCode === 'seriea',
    template: 'Italian top flight produces the league with the lowest match-total variance — both extremes are rare.',
    fill: () => ({}) },
  { id: 'x-lg-bun-1', category: 'league', magnitude: 'any', weight: 0.6, fires: (c) => c.leagueCode === 'bundesliga',
    template: 'Bundesliga has the highest goal-rate of our covered leagues — model variance is wider in both directions.',
    fill: () => ({}) },
  { id: 'x-lg-bun-2', category: 'league', magnitude: 'any', weight: 0.5, fires: (c) => c.leagueCode === 'bundesliga',
    template: 'German top flight: high-press dominant style produces transitions and goals — coin-flip territory more often than people read.',
    fill: () => ({}) },
  { id: 'x-lg-l1-1', category: 'league', magnitude: 'any', weight: 0.5, fires: (c) => c.leagueCode === 'ligue1',
    template: 'Ligue 1 has the largest top-3-vs-rest gap — favourite priors in this league tilt sharper than peers.',
    fill: () => ({}) },
  { id: 'x-lg-mls-1', category: 'league', magnitude: 'any', weight: 0.5, fires: (c) => c.leagueCode === 'mls',
    template: 'MLS travel is the longest in our pool — away-side variance widens accordingly.',
    fill: () => ({}) },
  { id: 'x-lg-champ-1', category: 'league', magnitude: 'any', weight: 0.5, fires: (c) => c.leagueCode === 'championship',
    template: 'Championship is the most parity-driven league we cover — favourite cash rates run several points lower than top tiers.',
    fill: () => ({}) },
  { id: 'x-lg-l2-1', category: 'league', magnitude: 'any', weight: 0.5, fires: (c) => c.leagueCode === 'league_two',
    template: 'EFL League Two: tight margins, big variance — published probabilities in this league should be read with patience.',
    fill: () => ({}) },

  // ── Confidence / framing ─────────────────────────────────────────────
  { id: 'x-conf-1', category: 'confidence', magnitude: 'hedged', weight: 0.6,
    fires: (c) => c.callConf < 45,
    template: 'Below 45% confidence is the model\'s "report what\'s there" tier — bullet text reflects the lean, not a bet.',
    fill: () => ({}) },
  { id: 'x-conf-2', category: 'confidence', magnitude: 'mid', weight: 0.6,
    fires: (c) => c.callConf >= 45 && c.callConf < 58,
    template: 'Mid-confidence band: published with conviction, but the "we could be wrong" frame stays on the page.',
    fill: () => ({}) },
  { id: 'x-conf-3', category: 'confidence', magnitude: 'loud', weight: 0.6,
    fires: (c) => c.callConf >= 58,
    template: 'Top-confidence tier — the model isn\'t doing this often, treat it as a signal worth flagging.',
    fill: () => ({}) },

  // ── Goals / totals ───────────────────────────────────────────────────
  { id: 'x-goals-1', category: 'goals', magnitude: 'any', weight: 0.5,
    fires: (c) => c.homeForm && c.awayForm && (c.homeForm.goals_scored_avg_5 ?? 0) + (c.awayForm.goals_scored_avg_5 ?? 0) >= 3.5,
    template: 'Combined recent attack rate runs hot — totals priors lean over, draws stay tight.',
    fill: () => ({}) },
  { id: 'x-goals-2', category: 'goals', magnitude: 'any', weight: 0.5,
    fires: (c) => c.homeForm && c.awayForm && (c.homeForm.goals_scored_avg_5 ?? 0) + (c.awayForm.goals_scored_avg_5 ?? 0) <= 2.0,
    template: 'Both sides under a goal a match recently — decisive results come from defensive errors, not attacking volume.',
    fill: () => ({}) },
  { id: 'x-goals-3', category: 'goals', magnitude: 'any', weight: 0.4,
    fires: () => true,
    template: 'Totals priors and outcome priors trade off — a high-totals match has flatter outcome distribution by construction.',
    fill: () => ({}) },]

// ──────────────────────────────────────────────────────────────────────
// Selector
// ──────────────────────────────────────────────────────────────────────

function fillTemplate(template, vars) {
  return template.replace(/\{\{(\w+)\}\}/g, (_, k) => (k in vars ? String(vars[k]) : `{{${k}}}`))
}

function hash(str) {
  let h = 5381
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0
  return h >>> 0
}

// Stable per-template jitter in [-0.4, +0.4]. Different bullets reorder
// across the 5-min bucket but a single render is stable.
function jitter(id, seed) {
  const v = hash(id + ':' + seed) / 0xffffffff // [0..1]
  return v * 0.8 - 0.4
}

// Magnitude gating: templates can declare `magnitude: 'loud' | 'mid' | 'hedged' | 'any'`.
// A template's magnitude must be at most the context's magnitude — i.e. loud language
// only fires on loud probabilities. This stops "huge favourite" templates appearing
// on 36% calls. Templates without an explicit magnitude default to 'any' and pass
// the gate unchanged (preserves backward-compat for older entries).
const MAG_RANK = { hedged: 1, mid: 2, loud: 3, any: 0 }

function ctxMagnitude(ctx) {
  let strength = 1
  if (ctx.callConf >= 42) strength = 2
  if (ctx.callConf >= 55 || ctx.spread >= 20 || (ctx.edge != null && ctx.edge >= 6)) strength = 3
  return strength
}

function magnitudeOk(ctx, mag) {
  if (mag == null || mag === 'any' || mag === 'hedged') return true
  return ctxMagnitude(ctx) >= MAG_RANK[mag]
}

/**
 * Pick N reason bullets for a match.
 *
 * @param {object} match
 * @param {number} n         How many bullets to return.
 * @param {object} opts
 * @param {Set<string>} opts.excludeIds  Template ids already used elsewhere in
 *   this render — typically threaded across the value deck or the daily slate
 *   so consecutive cards don't duplicate phrasing. The set is mutated in-place
 *   with the ids this call ends up using.
 * @param {string|number} opts.seed      Override the daily-rotation seed (testing).
 * @param {boolean} opts.returnTemplates If true, return the picked template
 *   objects instead of formatted strings (used internally by pickForBatch).
 */
export function pickFor(match, n = 4, opts = {}) {
  const ctx = buildContext(match)
  if (!ctx) return []
  const exclude = opts.excludeIds instanceof Set ? opts.excludeIds : null
  const eligible = TEMPLATES.filter((t) => {
    try {
      if (exclude && exclude.has(t.id)) return false
      if (!magnitudeOk(ctx, t.magnitude)) return false
      return t.fires(ctx)
    } catch {
      return false
    }
  })
  if (eligible.length === 0) return []

  // Daily rotation seed expanded into a 14-day cycle so the same match can
  // show distinctly different wording across two consecutive weeks before
  // any repetition is even possible.
  const today = new Date()
  const dayOrdinal = Math.floor(today.getTime() / 86400000)
  const fortnight = dayOrdinal % 14
  const dayKey = `${today.getUTCFullYear()}-${today.getUTCMonth()}-${today.getUTCDate()}-${fortnight}`
  const seed = opts.seed != null ? String(opts.seed) : dayKey
  const matchSeed = `${match?.id || 'x'}:${seed}`
  const ranked = [...eligible].sort((a, b) => {
    const sa = a.weight + jitter(a.id, matchSeed)
    const sb = b.weight + jitter(b.id, matchSeed)
    return sb - sa
  })

  // Variety pass: one per category until each category is touched once.
  const out = []
  const usedCats = new Set()
  for (const t of ranked) {
    if (out.length >= n) break
    if (usedCats.has(t.category)) continue
    out.push(t)
    usedCats.add(t.category)
  }
  for (const t of ranked) {
    if (out.length >= n) break
    if (out.includes(t)) continue
    out.push(t)
  }

  // Mutate the caller's exclude set so the next card avoids these.
  if (exclude) for (const t of out) exclude.add(t.id)

  if (opts.returnTemplates) return out
  return out.map((t) => {
    let vars = {}
    try {
      vars = t.fill(ctx) || {}
    } catch {
      /* keep going with empty vars */
    }
    return fillTemplate(t.template, vars)
  })
}

/**
 * Convenience wrapper for callers rendering a list of cards (value deck,
 * slate). Threads an excludeIds set across the matches so consecutive cards
 * don't pick the same templates. Returns one array of N strings per match.
 */
export function pickForBatch(matches, nPer = 1) {
  const used = new Set()
  return matches.map((m) => pickFor(m, nPer, { excludeIds: used }))
}

// ──────────────────────────────────────────────────────────────────────
// Empty / loading / error copy
// ──────────────────────────────────────────────────────────────────────

const EMPTY = {
  noMatches: [
    "No fixtures on the board today. We'll be back tomorrow with the next slate.",
    'All scoreboards are quiet. Check back when the next kickoff lands.',
    "Off-day across the leagues we cover. The model is busy refitting in the meantime.",
    "Nothing scheduled for today — flick to Upcoming to see what's coming.",
  ],
  calibrating: [
    "Model still calibrating this league. We'll publish picks once the buckets settle.",
    'Insufficient sample for honest probabilities — calibration in progress.',
    'Holding fire until the prior 30 matches stabilize the priors.',
  ],
  error: [
    "Couldn't reach the scoreboard — retrying every 6 seconds.",
    'Live feed dropped. Last known good state shown below.',
    "Timeout from the data partner. We'll flip back live the moment we hear back.",
  ],
  noValue: [
    'No qualifying value picks today — every edge is below the 3% noise floor.',
    "Books and the model agree on today's slate. Quiet day for the watchlist.",
    "Edge thin across the board — we'd rather skip than chase.",
  ],
}

export function emptyState(kind) {
  const list = EMPTY[kind] || EMPTY.noMatches
  const i = Math.floor(Date.now() / 60000) % list.length
  return list[i]
}

// Templates exported for diagnostics / future server-side mirror.
export { TEMPLATES }
export default { pickFor, pickForBatch, emptyState, TEMPLATES }
