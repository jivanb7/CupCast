// Best-effort lookups for fields the backend doesn't yet expose cleanly:
//   - 3-letter team shorts (the API copies the full name into short_name for
//     most teams, so we override the well-known ones and derive the rest)
//   - home venue (no backend column today)
//
// Long-term these should live on the Team model in the DB. Until then this
// keeps the editorial chrome filled in for the top-flight slate.

const SHORT_OVERRIDES = {
  // Premier League
  'arsenal': 'ARS', 'arsenal fc': 'ARS',
  'aston villa': 'AVL', 'aston villa fc': 'AVL',
  'brighton & hove albion': 'BHA', 'brighton': 'BHA',
  'burnley': 'BUR', 'burnley fc': 'BUR',
  'chelsea': 'CHE', 'chelsea fc': 'CHE',
  'crystal palace': 'CRY',
  'everton': 'EVE', 'everton fc': 'EVE',
  'fulham': 'FUL', 'fulham fc': 'FUL',
  'leeds united': 'LEE', 'leeds': 'LEE',
  'liverpool': 'LIV', 'liverpool fc': 'LIV',
  'manchester city': 'MCI', 'man city': 'MCI', 'manchester city fc': 'MCI',
  'manchester united': 'MUN', 'man united': 'MUN', 'man utd': 'MUN', 'manchester united fc': 'MUN',
  'newcastle united': 'NEW', 'newcastle': 'NEW',
  'nottingham forest': 'NFO', 'nottm forest': 'NFO',
  'tottenham hotspur': 'TOT', 'tottenham': 'TOT', 'spurs': 'TOT',
  'west ham united': 'WHU', 'west ham': 'WHU',
  'wolverhampton wanderers': 'WOL', 'wolves': 'WOL',
  'bournemouth': 'BOU', 'afc bournemouth': 'BOU',
  'brentford': 'BRE', 'brentford fc': 'BRE',

  // La Liga
  'real madrid': 'RMA', 'real madrid cf': 'RMA',
  'fc barcelona': 'BAR', 'barcelona': 'BAR', 'barca': 'BAR',
  'atletico madrid': 'ATM', 'atlético madrid': 'ATM', 'atlético de madrid': 'ATM', 'atletico de madrid': 'ATM',
  'sevilla': 'SEV', 'sevilla fc': 'SEV',
  'real sociedad': 'RSO',
  'real betis': 'BET', 'real betis balompié': 'BET',
  'villarreal': 'VIL', 'villarreal cf': 'VIL',
  'valencia': 'VAL', 'valencia cf': 'VAL',
  'celta vigo': 'CEL', 'celta de vigo': 'CEL', 'rc celta': 'CEL',
  'athletic club': 'ATH', 'athletic bilbao': 'ATH',
  'getafe': 'GET',
  'osasuna': 'OSA',
  'rayo vallecano': 'RAY',

  // Serie A
  'inter': 'INT', 'inter milan': 'INT', 'internazionale': 'INT', 'fc internazionale': 'INT',
  'juventus': 'JUV', 'juventus fc': 'JUV',
  'ac milan': 'MIL', 'milan': 'MIL',
  'napoli': 'NAP', 'ssc napoli': 'NAP',
  'as roma': 'ROM', 'roma': 'ROM',
  'lazio': 'LAZ', 'ss lazio': 'LAZ',
  'atalanta': 'ATA', 'atalanta bc': 'ATA',
  'fiorentina': 'FIO', 'acf fiorentina': 'FIO',
  'torino': 'TOR', 'torino fc': 'TOR',

  // Bundesliga
  'bayern munich': 'BAY', 'bayern münchen': 'BAY', 'fc bayern münchen': 'BAY', 'fc bayern munich': 'BAY',
  'borussia dortmund': 'DOR', 'dortmund': 'DOR', 'bvb': 'DOR',
  'bayer leverkusen': 'LEV', 'bayer 04 leverkusen': 'LEV', 'leverkusen': 'LEV',
  'rb leipzig': 'RBL', 'red bull leipzig': 'RBL',
  'borussia mönchengladbach': 'BMG', 'mönchengladbach': 'BMG',
  'eintracht frankfurt': 'SGE', 'frankfurt': 'SGE',
  'vfb stuttgart': 'STU', 'stuttgart': 'STU',
  'wolfsburg': 'WOB', 'vfl wolfsburg': 'WOB',

  // Ligue 1
  'paris saint-germain': 'PSG', 'psg': 'PSG', 'paris sg': 'PSG',
  'olympique de marseille': 'OM', 'marseille': 'OM',
  'olympique lyonnais': 'OL', 'lyon': 'OL',
  'monaco': 'MON', 'as monaco': 'MON',
  'lille': 'LIL', 'losc lille': 'LIL',
  'nice': 'NIC', 'ogc nice': 'NIC',
  'rennes': 'REN', 'stade rennais': 'REN',

  // Eredivisie
  'ajax': 'AJX', 'ajax amsterdam': 'AJX',
  'psv': 'PSV', 'psv eindhoven': 'PSV',
  'feyenoord': 'FEY', 'feyenoord rotterdam': 'FEY',

  // MLS
  'los angeles galaxy': 'LAG', 'la galaxy': 'LAG',
  'real salt lake': 'RSL',
  'inter miami cf': 'MIA', 'inter miami': 'MIA',
  'atlanta united fc': 'ATL', 'atlanta united': 'ATL',
  'seattle sounders fc': 'SEA', 'seattle sounders': 'SEA',
  'lafc': 'LAF', 'los angeles fc': 'LAF',
  'd.c. united': 'DCU', 'dc united': 'DCU',
  'nashville sc': 'NSH',
  'columbus crew': 'CLB',
  'new york city fc': 'NYC', 'nycfc': 'NYC',
  'new york red bulls': 'RBNY',
  'cf montréal': 'MTL', 'cf montreal': 'MTL',
  'toronto fc': 'TFC',
}

const NOISE_TOKENS = new Set([
  'fc', 'cf', 'afc', 'sc', 'ac', 'ssc', 'as', 'ss', 'cd', 'ud', 'rcd',
  'club', 'de', 'the', 'fk', 'rc', 'ka', 'calcio', 'futbol',
])

function clean(name) {
  return String(name || '').trim().toLowerCase()
}

// Returns the curated override (3-letter code) for a team name, or null
// if there's no override entry. Strips a trailing noise suffix as a second
// pass so "Real Madrid CF" matches the "real madrid" entry.
export function shortOverride(fullName) {
  if (!fullName) return null
  const key = clean(fullName)
  if (SHORT_OVERRIDES[key]) return SHORT_OVERRIDES[key]
  for (const tok of NOISE_TOKENS) {
    if (key.endsWith(' ' + tok)) {
      const trimmed = key.slice(0, -(tok.length + 1)).trim()
      if (SHORT_OVERRIDES[trimmed]) return SHORT_OVERRIDES[trimmed]
    }
  }
  return null
}

export function shortFor(fullName) {
  if (!fullName) return '???'
  const override = shortOverride(fullName)
  if (override) return override
  const key = clean(fullName)
  // Generic derivation: drop noise tokens, take initials of remaining words.
  const words = key
    .replace(/[^a-zà-ÿ\s]/gi, ' ')
    .split(/\s+/)
    .filter((w) => w && !NOISE_TOKENS.has(w))
  if (words.length === 0) return clean(fullName).slice(0, 3).toUpperCase() || '???'
  if (words.length === 1) return words[0].slice(0, 3).toUpperCase()
  if (words.length === 2) {
    // Two-word teams: first three chars of the longer word usually beats
    // initials. Port Vale → POR, Real Madrid → REA, Bayern Munich → BAY.
    // Whichever word is at least 3 chars long wins.
    const longer = words[0].length >= 3 ? words[0] : words[1]
    return longer.slice(0, 3).toUpperCase()
  }
  // 3+ words: take initials of first three.
  return (words[0][0] + words[1][0] + words[2][0]).toUpperCase()
}

const VENUE_BY_TEAM = {
  // Premier League
  'arsenal': 'Emirates',
  'aston villa': 'Villa Park',
  'brighton': 'Amex',
  'chelsea': 'Stamford Bridge',
  'crystal palace': 'Selhurst Park',
  'everton': 'Goodison Park',
  'fulham': 'Craven Cottage',
  'liverpool': 'Anfield',
  'manchester city': 'Etihad',
  'manchester united': 'Old Trafford',
  'newcastle': "St. James' Park",
  'nottingham forest': 'City Ground',
  'tottenham': 'Tottenham Hotspur Stadium',
  'west ham': 'London Stadium',
  'wolves': 'Molineux',
  'bournemouth': 'Vitality',
  'brentford': 'Gtech Community',
  // La Liga
  'real madrid': 'Bernabéu',
  'barcelona': 'Camp Nou',
  'atletico madrid': 'Metropolitano',
  'sevilla': 'Sánchez-Pizjuán',
  'real sociedad': 'Anoeta',
  'real betis': 'Benito Villamarín',
  'villarreal': 'Estadio de la Cerámica',
  'valencia': 'Mestalla',
  'celta vigo': 'Balaídos',
  'athletic club': 'San Mamés',
  // Serie A
  'inter': 'San Siro',
  'ac milan': 'San Siro',
  'juventus': 'Allianz Stadium',
  'napoli': 'Maradona',
  'as roma': 'Olimpico',
  'lazio': 'Olimpico',
  'atalanta': 'Gewiss',
  'fiorentina': 'Franchi',
  // Bundesliga
  'bayern munich': 'Allianz Arena',
  'borussia dortmund': 'Signal Iduna',
  'bayer leverkusen': 'BayArena',
  'rb leipzig': 'Red Bull Arena',
  // Ligue 1
  'paris saint-germain': 'Parc des Princes',
  'olympique de marseille': 'Vélodrome',
  'olympique lyonnais': 'Groupama',
  'monaco': 'Louis II',
  // Eredivisie
  'ajax': 'Johan Cruyff Arena',
  'psv': 'Philips Stadion',
  'feyenoord': 'De Kuip',
}

export function venueFor(homeTeamName) {
  if (!homeTeamName) return ''
  const key = clean(homeTeamName)
  if (VENUE_BY_TEAM[key]) return VENUE_BY_TEAM[key]
  for (const tok of NOISE_TOKENS) {
    if (key.endsWith(' ' + tok)) {
      const trimmed = key.slice(0, -(tok.length + 1)).trim()
      if (VENUE_BY_TEAM[trimmed]) return VENUE_BY_TEAM[trimmed]
    }
  }
  return ''
}

// Backend league_code → short label used by the design's rail/eyebrows.
// Falls back to the league_name when no mapping is registered.
const LEAGUE_SHORT = {
  epl: 'EPL',
  laliga: 'La Liga',
  seriea: 'Serie A',
  bundesliga: 'Bundesliga',
  ligue1: 'Ligue 1',
  ucl: 'UCL',
  eredivisie: 'Eredivisie',
  mls: 'MLS',
  worldcup: 'WC26',
  championship: 'EFL Champ',
  league_one: 'EFL L1',
  league_two: 'EFL L2',
  national_league: 'Nat Lge',
}

export function leagueShortFor(code, name) {
  if (code && LEAGUE_SHORT[String(code).toLowerCase()]) {
    return LEAGUE_SHORT[String(code).toLowerCase()]
  }
  return name || code || ''
}

const STAGE_LABELS = {
  group: 'Group Stage',
  r32: 'Round of 32',
  r16: 'Round of 16',
  qf: 'Quarterfinal',
  sf: 'Semifinal',
  final: 'Final',
  '3rd-place': '3rd-Place Playoff',
}

export function formatStage(apiStage, groupLabel) {
  if (!apiStage) return ''
  const k = String(apiStage).toLowerCase()
  if (k === 'group' && groupLabel) return `Group ${groupLabel}`
  return STAGE_LABELS[k] || apiStage
}
