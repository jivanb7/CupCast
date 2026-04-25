/**
 * countryMap — derives a country/competition slug from a match.
 *
 * The Dashboard's country tiles and the Matches page filter pill bar
 * use the same slug vocabulary:
 *   england | spain | italy | germany | france | usa | ucl | world-cup | rest
 *
 * We don't have a canonical country code on the league row, so we
 * keyword-match on league_name. Any league we don't recognise gets
 * bucketed into 'rest'.
 */

const RULES = [
  { slug: 'world-cup', test: (s) => /world\s*cup|fifa/i.test(s) },
  { slug: 'ucl', test: (s) => /champions\s*league|ucl/i.test(s) },
  {
    // 'England' is intentionally narrowed to the English Premier League only.
    // Sub-leagues (Championship, League One/Two, National League, FA Cup)
    // bucket into 'rest' so the demo stays focused on top-flight matches.
    slug: 'england',
    test: (s) => /english\s*premier\s*league|^premier\s*league$/i.test(s),
  },
  { slug: 'spain', test: (s) => /la\s*liga|copa\s*del|spanish/i.test(s) },
  { slug: 'italy', test: (s) => /serie\s*a|coppa\s*italia|italian/i.test(s) },
  { slug: 'germany', test: (s) => /bundesliga|german/i.test(s) },
  { slug: 'france', test: (s) => /ligue\s*1|coupe\s*de\s*france|french/i.test(s) },
  { slug: 'usa', test: (s) => /\bmls\b|major\s*league\s*soccer|us\s*open\s*cup|usa/i.test(s) },
]

export function leagueNameToSlug(leagueName) {
  if (!leagueName) return 'rest'
  for (const rule of RULES) {
    if (rule.test(leagueName)) return rule.slug
  }
  return 'rest'
}

export function matchToCountrySlug(match) {
  if (!match) return 'rest'
  // Backend league code 'worldcup' is authoritative for the tournament
  if (match.league_code === 'worldcup' || match.league_code === 'WORLDCUP') return 'world-cup'
  if (match.league_code === 'UCL') return 'ucl'
  return leagueNameToSlug(match.league_name)
}
