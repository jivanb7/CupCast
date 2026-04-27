// CupCast canonical mock data — ported from design_handoff_cupcast/data.jsx.
// Helpers compute callKey, callConf, valueCall, fairOdds, marketOdds so all
// pages agree on the semantics.

export const TEAMS = {
  RMA: { name: 'Real Madrid', short: 'RMA', color: '#FEBE10', league: 'La Liga', country: 'ES' },
  MCI: { name: 'Manchester City', short: 'MCI', color: '#6CABDD', league: 'EPL', country: 'EN' },
  LIV: { name: 'Liverpool', short: 'LIV', color: '#C8102E', league: 'EPL', country: 'EN' },
  ARS: { name: 'Arsenal', short: 'ARS', color: '#EF0107', league: 'EPL', country: 'EN' },
  CHE: { name: 'Chelsea', short: 'CHE', color: '#034694', league: 'EPL', country: 'EN' },
  TOT: { name: 'Tottenham', short: 'TOT', color: '#132257', league: 'EPL', country: 'EN' },
  BAR: { name: 'Barcelona', short: 'BAR', color: '#A50044', league: 'La Liga', country: 'ES' },
  ATM: { name: 'Atlético Madrid', short: 'ATM', color: '#CB3524', league: 'La Liga', country: 'ES' },
  SEV: { name: 'Sevilla', short: 'SEV', color: '#D71920', league: 'La Liga', country: 'ES' },
  VIL: { name: 'Villarreal', short: 'VIL', color: '#FFE667', league: 'La Liga', country: 'ES' },
  INT: { name: 'Inter', short: 'INT', color: '#0066CC', league: 'Serie A', country: 'IT' },
  JUV: { name: 'Juventus', short: 'JUV', color: '#1A1A1A', league: 'Serie A', country: 'IT' },
  MIL: { name: 'AC Milan', short: 'MIL', color: '#FB090B', league: 'Serie A', country: 'IT' },
  NAP: { name: 'Napoli', short: 'NAP', color: '#1B98E0', league: 'Serie A', country: 'IT' },
  BAY: { name: 'Bayern Munich', short: 'BAY', color: '#DC052D', league: 'Bundesliga', country: 'DE' },
  LEV: { name: 'Leverkusen', short: 'LEV', color: '#E32221', league: 'Bundesliga', country: 'DE' },
  DOR: { name: 'Dortmund', short: 'DOR', color: '#FDE100', league: 'Bundesliga', country: 'DE' },
  PSG: { name: 'PSG', short: 'PSG', color: '#004170', league: 'Ligue 1', country: 'FR' },
  MAR: { name: 'Marseille', short: 'MAR', color: '#2FAEE0', league: 'Ligue 1', country: 'FR' },
}

export const FLAGS = {
  EN: '🏴', ES: '🇪🇸', IT: '🇮🇹', DE: '🇩🇪', FR: '🇫🇷', US: '🇺🇸',
  BR: '🇧🇷', AR: '🇦🇷', PT: '🇵🇹', NL: '🇳🇱', BE: '🇧🇪', HR: '🇭🇷',
  JP: '🇯🇵', KR: '🇰🇷', AU: '🇦🇺', MA: '🇲🇦', SN: '🇸🇳', MX: '🇲🇽', CA: '🇨🇦',
}

export const LEAGUE_FLAG = {
  EPL: '🏴', 'La Liga': '🇪🇸', 'Serie A': '🇮🇹', Bundesliga: '🇩🇪',
  'Ligue 1': '🇫🇷', UCL: '⭐', WC26: '🏆', Eredivisie: '🇳🇱',
  'Liga MX': '🇲🇽', MLS: '🇺🇸',
}

export const toOdds = (p) => +(1 / p).toFixed(2)
export const fromOdds = (o) => 1 / o

export function decorate(m) {
  const probs = { H: m.probH, D: m.probD, A: m.probA }
  const callKey = ['H', 'D', 'A'].reduce((best, k) => (probs[k] > probs[best] ? k : best), 'H')
  const callTeam = callKey === 'H' ? m.home : callKey === 'A' ? m.away : 'Draw'
  const callShort = callKey === 'H' ? m.homeShort : callKey === 'A' ? m.awayShort : 'X'
  const callConf = probs[callKey]
  const marketProb = Math.max(0.02, Math.min(0.95, callConf / 100 - (m.edge || 0) / 100))
  const fairOdds = +(100 / callConf).toFixed(2)
  const marketOdds = +(1 / marketProb).toFixed(2)
  return {
    ...m,
    callKey,
    callTeam,
    callShort,
    callConf,
    valueCall: (m.edge || 0) >= 3.5,
    fairOdds,
    marketOdds,
  }
}

const matchesRaw = [
  { id: 'rma-mci', league: 'UCL', stage: 'QF · Leg 1', home: 'Real Madrid', homeShort: 'RMA', away: 'Manchester City', awayShort: 'MCI',
    kickoff: '21:00', venue: 'Bernabéu', minute: null, status: 'UPCOMING',
    probH: 38, probD: 27, probA: 35, edge: 4.2,
    why: [
      "City's xGA up 0.4 since defensive injuries to Dias and Aké",
      'Madrid 5W-1D in last 6 home knockouts vs English sides',
      'Both managers favor patient build-up: low first-half tempo expected',
      "Bernabéu crowd factor adds ~3% to Madrid's win prob in our model",
      'Public market underweighting Madrid — book at 2.50, fair at 2.63',
    ],
    h2h: ['Mar 26', 'Apr 25', 'Sep 24', 'Apr 24', 'Feb 23'] },
  { id: 'liv-ars', league: 'EPL', stage: 'Matchday 34', home: 'Liverpool', homeShort: 'LIV', away: 'Arsenal', awayShort: 'ARS',
    kickoff: '20:00', venue: 'Anfield', minute: 47, status: 'LIVE', score: '1-1',
    probH: 42, probD: 28, probA: 30, edge: 1.4 },
  { id: 'atm-sev', league: 'La Liga', stage: 'Matchday 33', home: 'Atlético Madrid', homeShort: 'ATM', away: 'Sevilla', awayShort: 'SEV',
    kickoff: '20:00', venue: 'Metropolitano', minute: null, status: 'UPCOMING',
    probH: 61, probD: 22, probA: 17, edge: 4.4 },
  { id: 'int-juv', league: 'Serie A', stage: 'Matchday 33', home: 'Inter', homeShort: 'INT', away: 'Juventus', awayShort: 'JUV',
    kickoff: '20:45', venue: 'San Siro', minute: null, status: 'UPCOMING',
    probH: 48, probD: 29, probA: 23, edge: 1.2 },
  { id: 'bay-lev', league: 'Bundesliga', stage: 'Matchday 31', home: 'Bayern Munich', homeShort: 'BAY', away: 'Leverkusen', awayShort: 'LEV',
    kickoff: '20:30', venue: 'Allianz', minute: null, status: 'UPCOMING',
    probH: 41, probD: 26, probA: 33, edge: 5.8 },
  { id: 'psg-mar', league: 'Ligue 1', stage: 'Matchday 32', home: 'PSG', homeShort: 'PSG', away: 'Marseille', awayShort: 'MAR',
    kickoff: '21:00', venue: 'Parc des Princes', minute: null, status: 'UPCOMING',
    probH: 67, probD: 19, probA: 14, edge: 0.8 },
  { id: 'che-tot', league: 'EPL', stage: 'Matchday 34', home: 'Chelsea', homeShort: 'CHE', away: 'Tottenham', awayShort: 'TOT',
    kickoff: '17:30', venue: 'Stamford Bridge', minute: 72, status: 'LIVE', score: '2-0',
    probH: 78, probD: 14, probA: 8, edge: 3.3 },
  { id: 'mil-nap', league: 'Serie A', stage: 'Matchday 33', home: 'AC Milan', homeShort: 'MIL', away: 'Napoli', awayShort: 'NAP',
    kickoff: '21:45', venue: 'San Siro', minute: null, status: 'UPCOMING',
    probH: 36, probD: 28, probA: 36, edge: 7.1 },
  { id: 'bar-vil', league: 'La Liga', stage: 'Matchday 33', home: 'Barcelona', homeShort: 'BAR', away: 'Villarreal', awayShort: 'VIL',
    kickoff: '22:00', venue: 'Camp Nou', minute: null, status: 'UPCOMING',
    probH: 64, probD: 21, probA: 15, edge: 1.9 },
]

export const matches = matchesRaw.map(decorate)
export const marquee = matches[0]

const wcTeams = [
  ['Argentina', 'ARG', '#75AADB', 'AR'], ['Spain', 'ESP', '#C60B1E', 'ES'],
  ['France', 'FRA', '#0055A4', 'FR'], ['Brazil', 'BRA', '#FEDF00', 'BR'],
  ['England', 'ENG', '#FFFFFF', 'EN'], ['Germany', 'GER', '#FFCE00', 'DE'],
  ['Portugal', 'POR', '#006600', 'PT'], ['Netherlands', 'NED', '#FF6600', 'NL'],
  ['Belgium', 'BEL', '#E30613', 'BE'], ['Croatia', 'CRO', '#FF0000', 'HR'],
  ['Italy', 'ITA', '#0066CC', 'IT'], ['USA', 'USA', '#3C3B6E', 'US'],
  ['Mexico', 'MEX', '#006847', 'MX'], ['Canada', 'CAN', '#FF0000', 'CA'],
  ['Japan', 'JPN', '#BC002D', 'JP'], ['Korea', 'KOR', '#003478', 'KR'],
  ['Australia', 'AUS', '#FFCD00', 'AU'], ['Morocco', 'MAR', '#C1272D', 'MA'],
  ['Senegal', 'SEN', '#00853F', 'SN'],
]

// Deterministic per-group probability derived from a seeded hash so SSR/CSR
// renders match — and so the layout doesn't reshuffle on every reload.
function seededProb(g, k) {
  const s = (g.charCodeAt(0) * 31 + k) >>> 0
  const v = (s * 9301 + 49297) % 233280
  return Math.round(30 + (v / 233280) * 40)
}

export const wcGroups = 'ABCDEFGHIJKL'.split('').map((g, i) => {
  const slate = []
  for (let k = 0; k < 4; k++) {
    const [name, short, color, country] = wcTeams[(i * 4 + k) % wcTeams.length]
    slate.push({ name, short, color, country, prob: seededProb(g, k) })
  }
  return { letter: g, teams: slate }
})

export const valuePicks = matches
  .filter((m) => m.valueCall)
  .sort((a, b) => b.edge - a.edge)
  .map((m) => ({
    id: m.id,
    match: `${m.home} v ${m.away}`,
    league: m.league,
    pick: m.callTeam,
    edge: m.edge,
    conf: m.callConf,
    fairOdds: m.fairOdds,
    marketOdds: m.marketOdds,
    kickoff: m.kickoff,
    reason: m.why ? m.why[0] : "Market underweights the model's call.",
  }))

export const calibration = Array.from({ length: 10 }, (_, i) => ({
  bucket: 5 + i * 10,
  realized: Math.max(0, Math.min(100, 5 + i * 10 + Math.sin(i * 0.7) * 4)),
}))

export const rolling = Array.from({ length: 90 }, (_, i) => {
  const base = 60 + Math.sin(i * 0.13) * 5 + Math.cos(i * 0.07) * 4
  return { d: i, acc: +base.toFixed(1) }
})

export const lastWeek = rolling.slice(-8).map((r, i) => ({
  d: ['Apr 19', 'Apr 20', 'Apr 21', 'Apr 22', 'Apr 23', 'Apr 24', 'Apr 25', 'Apr 26'][i],
  acc: Math.round(r.acc),
}))

export const perLeague = [
  { name: 'EPL', flag: '🏴', acc: 71.4, picks: 142, brier: 0.176, delta: +2.1, sample: 'win+win+loss+win+win' },
  { name: 'La Liga', flag: '🇪🇸', acc: 66.7, picks: 134, brier: 0.193, delta: -0.4, sample: 'win+loss+win+win+draw' },
  { name: 'Serie A', flag: '🇮🇹', acc: 69.0, picks: 128, brier: 0.181, delta: +1.0, sample: 'win+win+win+loss+win' },
  { name: 'Bundesliga', flag: '🇩🇪', acc: 62.8, picks: 118, brier: 0.205, delta: -2.3, sample: 'win+loss+loss+win+draw' },
  { name: 'Ligue 1', flag: '🇫🇷', acc: 64.1, picks: 124, brier: 0.198, delta: +0.6, sample: 'win+win+loss+win+win' },
  { name: 'UCL', flag: '⭐', acc: 70.2, picks: 56, brier: 0.179, delta: +3.4, sample: 'win+win+win+draw+win' },
  { name: 'Eredivisie', flag: '🇳🇱', acc: 65.4, picks: 98, brier: 0.196, delta: -0.8, sample: 'loss+win+win+win+loss' },
]

export const today = {
  accuracy: 68.4,
  accuracyDelta: +1.2,
  picksHit: 9,
  picksMade: 14,
  valueEdge: 4.7,
  rolling30: 64.1,
  rolling90: 65.7,
  calibration: 0.97,
  brier: 0.184,
  logloss: 0.512,
  lastUpdated: 12,
}

export const CC = {
  TEAMS, FLAGS, LEAGUE_FLAG, matches, marquee, today, valuePicks,
  calibration, rolling, lastWeek, perLeague, wcGroups, toOdds, fromOdds, decorate,
}

export default CC
