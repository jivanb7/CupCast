"""
ml/src/team_name_mapping.py
============================
Canonical team name resolution.

All data sources use different names for the same team. This module provides
a single source of truth: every raw name maps to a canonical name. The
canonical name is what gets stored in the database and used for all feature
joins.

Usage:
    from ml.src.team_name_mapping import resolve_team_name, TEAM_NAME_MAP

    canonical = resolve_team_name("Man United", source="football_data_uk")
    # returns: "Manchester United"

IMPORTANT:
    - If a name is NOT in the map, resolve_team_name() returns the raw name
      unchanged AND logs a warning. This is intentional — never silently drop
      data. The data_processing step has a validation pass that collects all
      unmapped names and writes them to data/processed/unmapped_team_names.txt.
      Review this file after each ingestion run and add new aliases here.

    - Team names in this map should match the canonical_name column in the
      teams database table.

    - Use EXACT strings from each source — copy-paste from the CSV, do not
      guess the capitalization.
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Master alias → canonical name mapping
# ---------------------------------------------------------------------------
# Key: raw name as it appears in the source data
# Value: canonical name (matches teams.canonical_name in the database)
TEAM_NAME_MAP: dict[str, str] = {
    # ---- English Premier League (football-data.co.uk) ----
    "Man United": "Manchester United",
    "Man City": "Manchester City",
    "Nott'm Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    "Sheffield Utd": "Sheffield United",
    "Sheffield United": "Sheffield United",
    "Wolverhampton": "Wolverhampton Wanderers",
    "Wolves": "Wolverhampton Wanderers",
    "West Ham": "West Ham United",
    "Newcastle": "Newcastle United",
    "Spurs": "Tottenham Hotspur",
    "Tottenham": "Tottenham Hotspur",
    "Brighton": "Brighton & Hove Albion",
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Ipswich": "Ipswich Town",
    "Leicester": "Leicester City",
    "Bournemouth": "AFC Bournemouth",
    "QPR": "Queens Park Rangers",
    "Stoke": "Stoke City",
    "Sunderland": "Sunderland AFC",
    "Hull": "Hull City",
    "Swansea": "Swansea City",
    "Cardiff": "Cardiff City",
    "Burnley": "Burnley FC",
    "Watford": "Watford FC",
    "Huddersfield": "Huddersfield Town",
    "Norwich": "Norwich City",
    "Brentford": "Brentford FC",
    "Fulham": "Fulham FC",
    "Everton": "Everton FC",
    "Arsenal": "Arsenal FC",
    "Chelsea": "Chelsea FC",
    "Liverpool": "Liverpool FC",
    "Aston Villa": "Aston Villa FC",
    "Crystal Palace": "Crystal Palace FC",
    "Southampton": "Southampton FC",

    # ---- English Premier League / Championship extras ----
    "Middlesbrough": "Middlesbrough FC",
    "Portsmouth": "Portsmouth FC",
    "Wigan": "Wigan Athletic",
    "Birmingham": "Birmingham City",
    "Blackburn": "Blackburn Rovers",
    "Charlton": "Charlton Athletic",
    "West Brom": "West Bromwich Albion",
    "Bolton": "Bolton Wanderers",
    "Reading": "Reading FC",
    "Derby": "Derby County",
    "Blackpool": "Blackpool FC",
    "Leeds": "Leeds United",
    "Leeds United": "Leeds United",
    "Barnsley": "Barnsley FC",
    "Luton": "Luton Town",
    "Coventry": "Coventry City",
    "Millwall": "Millwall FC",
    "Preston": "Preston North End",
    "Rotherham": "Rotherham United",
    "Plymouth": "Plymouth Argyle",
    "Bristol City": "Bristol City FC",
    "Oxford United": "Oxford United FC",
    "Sheff Wed": "Sheffield Wednesday",
    "Sheffield Wednesday": "Sheffield Wednesday",
    "Peterborough": "Peterborough United",
    "Leyton Orient": "Leyton Orient FC",
    "Middlesboro": "Middlesbrough FC",
    "Burton": "Burton Albion",
    "Doncaster": "Doncaster Rovers",
    "Milton Keynes Dons": "Milton Keynes Dons",
    "Peterboro": "Peterborough United",
    "Scunthorpe": "Scunthorpe United",
    "Sheffield Weds": "Sheffield Wednesday",
    "Wrexham": "Wrexham AFC",
    "Wycombe": "Wycombe Wanderers",
    "Yeovil": "Yeovil Town",
    "Oxford": "Oxford United FC",

    # ---- La Liga (football-data.co.uk) ----
    "Barcelona": "FC Barcelona",
    "Real Madrid": "Real Madrid CF",
    "Atletico Madrid": "Atlético de Madrid",
    "Atl Madrid": "Atlético de Madrid",
    "Ath Madrid": "Atlético de Madrid",
    "Betis": "Real Betis",
    "Sevilla": "Sevilla FC",
    "Valencia": "Valencia CF",
    "Villarreal": "Villarreal CF",
    "Athletic Club": "Athletic Club Bilbao",
    "Ath Bilbao": "Athletic Club Bilbao",
    "Sociedad": "Real Sociedad",
    "Celta": "Celta de Vigo",
    "Getafe": "Getafe CF",
    "Vallecano": "Rayo Vallecano",
    "Rayo Vallecano": "Rayo Vallecano",
    "Osasuna": "CA Osasuna",
    "Girona": "Girona FC",
    "Alaves": "Deportivo Alavés",
    "Cadiz": "Cádiz CF",
    "Almeria": "UD Almería",
    "Mallorca": "RCD Mallorca",
    "Las Palmas": "UD Las Palmas",
    "Leganes": "CD Leganés",
    "Espanol": "RCD Espanyol",
    "Espanyol": "RCD Espanyol",
    "Valladolid": "Real Valladolid",
    "Granada": "Granada CF",
    "Eibar": "SD Eibar",
    "Levante": "Levante UD",
    "Dep La Coruna": "Deportivo La Coruña",
    "La Coruna": "Deportivo La Coruña",
    "Sp Gijon": "Sporting de Gijón",
    "Elche": "Elche CF",
    "Huesca": "SD Huesca",
    "Zaragoza": "Real Zaragoza",
    "Tenerife": "CD Tenerife",
    "Hercules": "Hércules CF",
    "Numancia": "CD Numancia",
    "Xerez": "Xerez CD",
    "Cordoba": "Córdoba CF",
    "Malaga": "Málaga CF",
    "Oviedo": "Real Oviedo",
    "Santander": "Racing de Santander",
    "Recreativo": "RC Recreativo",
    "Racing Santander": "Racing de Santander",
    "Sociedad B": "Real Sociedad B",
    "Castellon": "CD Castellón",

    # ---- Bundesliga (football-data.co.uk) ----
    "Bayern Munich": "FC Bayern München",
    "Dortmund": "Borussia Dortmund",
    "Leverkusen": "Bayer 04 Leverkusen",
    "RB Leipzig": "RasenBallsport Leipzig",
    "Frankfurt": "Eintracht Frankfurt",
    "Freiburg": "SC Freiburg",
    "Hoffenheim": "TSG 1899 Hoffenheim",
    "Wolfsburg": "VfL Wolfsburg",
    "Monchengladbach": "Borussia Mönchengladbach",
    "M'gladbach": "Borussia Mönchengladbach",
    "Ein Frankfurt": "Eintracht Frankfurt",
    "Union Berlin": "1. FC Union Berlin",
    "Stuttgart": "VfB Stuttgart",
    "Augsburg": "FC Augsburg",
    "Mainz": "1. FSV Mainz 05",
    "Mainz 05": "1. FSV Mainz 05",
    "Werder Bremen": "SV Werder Bremen",
    "Heidenheim": "1. FC Heidenheim",
    "St Pauli": "FC St. Pauli",
    "Holstein Kiel": "Holstein Kiel",
    "Hannover": "Hannover 96",
    "Hamburger SV": "Hamburger SV",
    "Schalke 04": "FC Schalke 04",
    "Hertha": "Hertha BSC",
    "Nurnberg": "1. FC Nürnberg",
    "Dusseldorf": "Fortuna Düsseldorf",
    "Paderborn": "SC Paderborn 07",
    "Darmstadt": "SV Darmstadt 98",
    "Greuther Furth": "SpVgg Greuther Fürth",
    "Ingolstadt": "FC Ingolstadt 04",
    "Koln": "1. FC Köln",
    "Braunschweig": "Eintracht Braunschweig",
    "Bielefeld": "Arminia Bielefeld",
    "Bochum": "VfL Bochum",
    "Kaiserslautern": "1. FC Kaiserslautern",
    "Cottbus": "Energie Cottbus",
    "FC Koln": "1. FC Köln",
    "Fortuna Dusseldorf": "Fortuna Düsseldorf",
    "Hamburg": "Hamburger SV",

    # ---- Serie A (football-data.co.uk) ----
    "Inter": "FC Internazionale Milano",
    "AC Milan": "AC Milan",
    "Milan": "AC Milan",
    "Juventus": "Juventus FC",
    "Napoli": "SSC Napoli",
    "AS Roma": "AS Roma",
    "Roma": "AS Roma",
    "Lazio": "SS Lazio",
    "Atalanta": "Atalanta BC",
    "Fiorentina": "ACF Fiorentina",
    "Torino": "Torino FC",
    "Bologna": "Bologna FC",
    "Udinese": "Udinese Calcio",
    "Genoa": "Genoa CFC",
    "Parma": "Parma Calcio 1913",
    "Sampdoria": "UC Sampdoria",
    "Cagliari": "Cagliari Calcio",
    "Lecce": "US Lecce",
    "Venezia": "Venezia FC",
    "Como": "Como 1907",
    "Verona": "Hellas Verona",
    "Monza": "AC Monza",
    "Sassuolo": "US Sassuolo",
    "Frosinone": "Frosinone Calcio",
    "Empoli": "FC Empoli",
    "Benevento": "Benevento Calcio",
    "Chievo": "AC ChievoVerona",
    "Spal": "SPAL 2013",
    "SPAL": "SPAL 2013",
    "Crotone": "FC Crotone",
    "Pescara": "Pescara Calcio",
    "Palermo": "US Città di Palermo",
    "Carpi": "Carpi FC",
    "Catania": "Calcio Catania",
    "Novara": "Novara Calcio",
    "Cesena": "AC Cesena",
    "Siena": "AC Siena",
    "Livorno": "AS Livorno",
    "Brescia": "Brescia Calcio",
    "Cremonese": "US Cremonese",
    "Pisa": "AC Pisa",
    "Bari": "SSC Bari",
    "Spezia": "Spezia Calcio",
    "Salernitana": "US Salernitana 1919",
    "Reggina": "Reggina Calcio",

    # ---- Ligue 1 (football-data.co.uk) ----
    "Paris SG": "Paris Saint-Germain",
    "PSG": "Paris Saint-Germain",
    "Lyon": "Olympique Lyonnais",
    "Marseille": "Olympique de Marseille",
    "Monaco": "AS Monaco",
    "Lille": "LOSC Lille",
    "Rennes": "Stade Rennais FC",
    "Nice": "OGC Nice",
    "Lens": "RC Lens",
    "Strasbourg": "RC Strasbourg Alsace",
    "Montpellier": "Montpellier HSC",
    "Nantes": "FC Nantes",
    "Reims": "Stade de Reims",
    "Toulouse": "Toulouse FC",
    "Le Havre": "Le Havre AC",
    "Brest": "Stade Brestois",
    "Angers": "SCO Angers",
    "St Etienne": "AS Saint-Étienne",
    "Lorient": "FC Lorient",
    "Metz": "FC Metz",
    "Bordeaux": "Girondins de Bordeaux",
    "Ajaccio": "AC Ajaccio",
    "Ajaccio GFCO": "GFC Ajaccio",
    "Auxerre": "AJ Auxerre",
    "Bastia": "SC Bastia",
    "Caen": "SM Caen",
    "Guingamp": "EA Guingamp",
    "Nancy": "AS Nancy",
    "Amiens": "Amiens SC",
    "Dijon": "Dijon FCO",
    "Troyes": "ESTAC Troyes",
    "Sochaux": "FC Sochaux-Montbéliard",
    "Valenciennes": "Valenciennes FC",
    "Arles": "AC Arles-Avignon",
    "Evian Thonon Gaillard": "Evian TG FC",
    "Clermont": "Clermont Foot 63",
    "Nimes": "Nîmes Olympique",
    "Paris FC": "Paris FC",

    # ---- MLS ----
    "LA Galaxy": "Los Angeles Galaxy",
    "LAFC": "Los Angeles FC",
    "NYCFC": "New York City FC",
    "NY Red Bulls": "New York Red Bulls",
    "Inter Miami": "Inter Miami CF",
    "DC United": "D.C. United",
    "Sporting KC": "Sporting Kansas City",
    "SJ Earthquakes": "San Jose Earthquakes",
    "Sounders": "Seattle Sounders FC",
    "Seattle Sounders": "Seattle Sounders FC",
    "Portland Timbers": "Portland Timbers FC",
    "Colorado Rapids": "Colorado Rapids FC",
    "New England": "New England Revolution",
    "Columbus Crew": "Columbus Crew SC",
    "Houston Dynamo": "Houston Dynamo FC",
    "CF Montreal": "CF Montréal",
    "Toronto": "Toronto FC",
    "Vancouver Whitecaps": "Vancouver Whitecaps FC",
    "Minnesota United": "Minnesota United FC",
    "Atlanta United": "Atlanta United FC",
    "NYRB": "New York Red Bulls",
    "FC Cincinnati": "FC Cincinnati",
    "Charlotte": "Charlotte FC",
    "St. Louis City": "St. Louis City SC",
    "San Diego FC": "San Diego FC",
    "Nashville SC": "Nashville SC",
    "Austin FC": "Austin FC",

    # ---- International (Kaggle / FIFA) ----
    "USA": "United States",
    "United States of America": "United States",
    "Korea Republic": "South Korea",
    "Korea DPR": "North Korea",
    "IR Iran": "Iran",
    "Türkiye": "Turkey",
    "Turkey": "Turkey",
    "Czechia": "Czech Republic",
    "Czech Republic": "Czech Republic",
    "Ivory Coast": "Côte d'Ivoire",
    "Cote d'Ivoire": "Côte d'Ivoire",
    "DR Congo": "Democratic Republic of Congo",
    "Congo DR": "Democratic Republic of Congo",
    "Cape Verde": "Cape Verde Islands",
    "Bosnia": "Bosnia and Herzegovina",
    "Bosnia Herzegovina": "Bosnia and Herzegovina",
    "Northern Ireland": "Northern Ireland",
    "Republic of Ireland": "Republic of Ireland",
    "China PR": "China",
    "Chinese Taipei": "Taiwan",
    "Curacao": "Curaçao",
    "Trinidad and Tobago": "Trinidad & Tobago",
    "St. Kitts and Nevis": "Saint Kitts and Nevis",
    "St. Lucia": "Saint Lucia",
    "St. Vincent / Grenadines": "Saint Vincent and the Grenadines",
    "Antigua and Barbuda": "Antigua & Barbuda",
    "São Tomé and Príncipe": "Sao Tome and Principe",
    "Eswatini": "Swaziland",  # historical name used in older data
    "North Macedonia": "North Macedonia",
    "FYR Macedonia": "North Macedonia",
    "Palestine": "Palestine",
}


def resolve_team_name(raw_name: str, source: str = "unknown") -> str:
    """
    Resolve a raw team name to its canonical form.

    Parameters
    ----------
    raw_name : str
        The team name as it appears in the source data (CSV, API response, etc.)
    source : str
        The data source identifier for logging purposes.
        E.g. 'football_data_uk', 'kaggle_intl', 'football_data_org'

    Returns
    -------
    str
        Canonical team name. Returns raw_name unchanged if no mapping exists
        (and logs a warning — these should be added to TEAM_NAME_MAP).
    """
    if raw_name in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[raw_name]

    # Try case-insensitive lookup as a fallback
    lower_map = {k.lower(): v for k, v in TEAM_NAME_MAP.items()}
    if raw_name.lower() in lower_map:
        canonical = lower_map[raw_name.lower()]
        logger.debug(
            "Case-insensitive match for '%s' -> '%s' (source: %s)",
            raw_name, canonical, source,
        )
        return canonical

    logger.warning(
        "Unmapped team name: '%s' (source: %s). Add to TEAM_NAME_MAP.",
        raw_name, source,
    )
    return raw_name


def validate_mapping_coverage(team_names: list[str], source: str = "unknown") -> list[str]:
    """
    Given a list of team names from a source, return those that are NOT in TEAM_NAME_MAP
    and also are NOT already canonical names (i.e., appear as values in TEAM_NAME_MAP).

    Use this during data processing to catch unmapped names before they cause
    silent feature join failures.

    Returns a list of unresolved team names.
    """
    canonical_names = set(TEAM_NAME_MAP.values())
    unresolved = []
    for name in team_names:
        if name not in TEAM_NAME_MAP and name not in canonical_names:
            unresolved.append(name)
    if unresolved:
        logger.warning(
            "%d unresolved team names from source '%s': %s",
            len(unresolved), source, unresolved[:20],
        )
    return unresolved
