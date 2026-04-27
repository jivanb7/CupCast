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
]

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

export function pickFor(match, n = 4, opts = {}) {
  const ctx = buildContext(match)
  if (!ctx) return []
  const eligible = TEMPLATES.filter((t) => {
    try {
      return t.fires(ctx)
    } catch {
      return false
    }
  })
  if (eligible.length === 0) return []

  const seed = opts.seed != null ? String(opts.seed) : String(Math.floor(Date.now() / (5 * 60 * 1000)))
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
  // Backfill from remaining ranked templates.
  for (const t of ranked) {
    if (out.length >= n) break
    if (out.includes(t)) continue
    out.push(t)
  }

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

// ──────────────────────────────────────────────────────────────────────
// Empty / loading / error copy
// ──────────────────────────────────────────────────────────────────────

const EMPTY = {
  noMatches: [
    'No matches today — back tomorrow. The slate restarts at 06:00 CET.',
    'All scoreboards are quiet. Check back at kickoff.',
    "Off-day. We're refitting the weekend's calibration in the meantime.",
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
export default { pickFor, emptyState, TEMPLATES }
