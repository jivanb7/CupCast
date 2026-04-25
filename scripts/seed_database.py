"""
scripts/seed_database.py
=========================
Seed the database with reference data AND historical match data from parquets.

What gets seeded:
  1. Leagues (epl, laliga, bundesliga, seriea, ligue1, mls, worldcup, championship)
  2. Club teams extracted from club_matches.parquet
  3. World Cup 2026 national teams (48 teams with confederation)
  4. Historical club matches from ml/data/processed/club_matches.parquet
  5. Upcoming fixtures from ml/data/processed/fixtures.parquet
  6. FIFA rankings from ml/data/processed/fifa_rankings.parquet

Run (from the cupcast/ project root):
  python scripts/seed_database.py

Idempotent: checks for existing records before inserting to avoid duplicates.
Safe to re-run.
"""

import os
import sys
from pathlib import Path
from datetime import date

# Resolve project root: this script lives at <project_root>/scripts/seed_database.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Add backend and ml to path so we can import their modules
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "ml"))

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.league import League
from models.team import Team, TeamNameAlias
from models.match import Match
from models.fifa_ranking import FifaRanking
from database import Base

# ── Database URL ──────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./cupcast_dev.db")

# For SQLite relative paths, resolve to an absolute path based on project root
if DATABASE_URL.startswith("sqlite:///./"):
    db_filename = DATABASE_URL[len("sqlite:///./"):]
    db_path = PROJECT_ROOT / "backend" / db_filename
    DATABASE_URL = f"sqlite:///{db_path}"

print(f"Connecting to: {DATABASE_URL}")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

Session = sessionmaker(bind=engine)

# ── Data paths ────────────────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "ml" / "data" / "processed"
CLUB_MATCHES_PATH = DATA_DIR / "club_matches.parquet"
FIXTURES_PATH = DATA_DIR / "fixtures.parquet"
FIFA_RANKINGS_PATH = DATA_DIR / "fifa_rankings.parquet"

# ── League code to DB code mapping ────────────────────────────────────────────
# Maps football-data.co.uk league codes → CupCast canonical league codes
LEAGUE_CODE_MAP = {
    "E0": "epl",
    "E1": "championship",
    "E2": "league_one",
    "E3": "league_two",
    "EC": "national_league",
    "SP1": "laliga",
    "I1": "seriea",
    "D1": "bundesliga",
    "F1": "ligue1",
    "UCL": "ucl",
}

LEAGUE_NAME_MAP = {
    "epl": "English Premier League",
    "championship": "English Championship",
    "league_one": "English League One",
    "league_two": "English League Two",
    "national_league": "English National League",
    "laliga": "La Liga",
    "seriea": "Serie A",
    "bundesliga": "Bundesliga",
    "ligue1": "Ligue 1",
    "ucl": "UEFA Champions League",
}

# Raw league code → canonical league code for fixture team resolution
FIXTURE_LEAGUE_GUESS = {
    # English lower league teams cannot be cleanly mapped without more data;
    # assign them to 'championship' as a catch-all for English club teams
}

# ── World Cup confederation map ───────────────────────────────────────────────
CONFEDERATION_MAP = {
    "Mexico": "CONCACAF", "South Africa": "CAF", "South Korea": "AFC",
    "Czech Republic": "UEFA", "Canada": "CONCACAF",
    "Bosnia and Herzegovina": "UEFA", "Qatar": "AFC", "Switzerland": "UEFA",
    "Brazil": "CONMEBOL", "Morocco": "CAF", "Haiti": "CONCACAF",
    "Scotland": "UEFA", "United States": "CONCACAF", "Paraguay": "CONMEBOL",
    "Australia": "AFC", "Turkey": "UEFA", "Germany": "UEFA",
    "Curaçao": "CONCACAF", "Côte d'Ivoire": "CAF", "Ecuador": "CONMEBOL",
    "Netherlands": "UEFA", "Japan": "AFC", "Sweden": "UEFA", "Tunisia": "CAF",
    "Belgium": "UEFA", "Egypt": "CAF", "Iran": "AFC", "New Zealand": "OFC",
    "Spain": "UEFA", "Cape Verde Islands": "CAF", "Saudi Arabia": "AFC",
    "Uruguay": "CONMEBOL", "France": "UEFA", "Senegal": "CAF", "Iraq": "AFC",
    "Norway": "UEFA", "Argentina": "CONMEBOL", "Algeria": "CAF",
    "Austria": "UEFA", "Jordan": "AFC", "Portugal": "UEFA",
    "Democratic Republic of Congo": "CAF", "Uzbekistan": "AFC",
    "Colombia": "CONMEBOL", "England": "UEFA", "Croatia": "UEFA",
    "Ghana": "CAF", "Panama": "CONCACAF",
}


# ── Step 1: Seed leagues ──────────────────────────────────────────────────────
def seed_leagues(session):
    leagues = [
        {"code": "epl", "name": "English Premier League", "country": "England", "season_format": "split_year"},
        {"code": "championship", "name": "English Championship", "country": "England", "season_format": "split_year"},
        {"code": "league_one", "name": "English League One", "country": "England", "season_format": "split_year"},
        {"code": "league_two", "name": "English League Two", "country": "England", "season_format": "split_year"},
        {"code": "national_league", "name": "English National League", "country": "England", "season_format": "split_year"},
        {"code": "laliga", "name": "La Liga", "country": "Spain", "season_format": "split_year"},
        {"code": "seriea", "name": "Serie A", "country": "Italy", "season_format": "split_year"},
        {"code": "bundesliga", "name": "Bundesliga", "country": "Germany", "season_format": "split_year"},
        {"code": "ligue1", "name": "Ligue 1", "country": "France", "season_format": "split_year"},
        {"code": "mls", "name": "MLS", "country": "USA", "season_format": "calendar_year"},
        {"code": "worldcup", "name": "FIFA World Cup", "country": None, "season_format": None},
        # UCL is a continental competition — country is None
        {"code": "ucl", "name": "UEFA Champions League", "country": None, "season_format": "split_year"},
    ]
    count = 0
    for l in leagues:
        existing = session.query(League).filter_by(code=l["code"]).first()
        if not existing:
            session.add(League(**l, is_active=True))
            count += 1
    session.commit()
    print(f"Seeded {count} leagues (skipped {len(leagues) - count} existing)")


def _resolve_team_with_alias(session, team_name: str):
    """Return an existing Team for ``team_name`` by checking canonical_name
    first, then the team_name_aliases table.

    Used by the parquet seeders so a legacy name encoded in historical data
    (e.g. "RasenBallsport Leipzig") resolves to its canonical row ("RB
    Leipzig") instead of being re-inserted as a duplicate.
    """
    if not team_name:
        return None
    team = session.query(Team).filter_by(canonical_name=team_name).first()
    if team:
        return team
    alias = (
        session.query(TeamNameAlias)
        .filter(TeamNameAlias.alias == team_name)
        .first()
    )
    if alias:
        return session.query(Team).filter_by(id=alias.team_id).first()
    return None


# ── Step 2: Seed club teams from parquet ─────────────────────────────────────
def seed_club_teams(session):
    """Extract all unique team names per league from club_matches.parquet."""
    if not CLUB_MATCHES_PATH.exists():
        print(f"WARNING: {CLUB_MATCHES_PATH} not found — skipping club team seed")
        return {}

    df = pd.read_parquet(CLUB_MATCHES_PATH)

    # Build league_id lookup
    league_id_map = {
        league.code: league.id
        for league in session.query(League).all()
    }

    team_id_map = {}  # canonical_name → team_id
    count = 0

    for raw_code, league_code in LEAGUE_CODE_MAP.items():
        league_id = league_id_map.get(league_code)
        if league_id is None:
            continue

        league_df = df[df["league_code"] == raw_code]
        teams = set(league_df["home_team"].tolist()) | set(league_df["away_team"].tolist())

        for team_name in sorted(teams):
            if team_name in team_id_map:
                continue
            # Alias-aware: a parquet row may use a legacy name (e.g.
            # "RasenBallsport Leipzig") that has been migrated into an alias
            # of the canonical row ("RB Leipzig"). Resolve via the alias
            # table before inserting, otherwise we'd recreate the duplicate
            # the merge migration just cleaned up.
            existing = _resolve_team_with_alias(session, team_name)
            if existing:
                team_id_map[team_name] = existing.id
                continue
            team = Team(
                canonical_name=team_name,
                short_name=team_name[:50],
                team_type="club",
                league_id=league_id,
            )
            session.add(team)
            session.flush()
            team_id_map[team_name] = team.id
            count += 1

    session.commit()
    print(f"Seeded {count} club teams")
    return team_id_map


# ── Step 3: Seed national teams (World Cup 2026) ──────────────────────────────
def seed_world_cup_teams(session):
    """Insert all 48 World Cup 2026 national teams."""
    from src.config import WORLD_CUP_2026_GROUPS

    worldcup_league = session.query(League).filter_by(code="worldcup").first()
    worldcup_league_id = worldcup_league.id if worldcup_league else None

    count = 0
    for _group, teams in WORLD_CUP_2026_GROUPS.items():
        for team_name in teams:
            existing = session.query(Team).filter_by(canonical_name=team_name).first()
            if existing:
                continue
            confederation = CONFEDERATION_MAP.get(team_name, "UEFA")
            team = Team(
                canonical_name=team_name,
                short_name=team_name[:50],
                team_type="national",
                league_id=worldcup_league_id,
                confederation=confederation,
            )
            session.add(team)
            count += 1

    session.commit()
    print(f"Seeded {count} national teams")


# ── Step 4: Seed historical club matches ─────────────────────────────────────
def seed_club_matches(session):
    """Load club_matches.parquet and insert completed historical matches."""
    if not CLUB_MATCHES_PATH.exists():
        print(f"WARNING: {CLUB_MATCHES_PATH} not found — skipping match seed")
        return

    df = pd.read_parquet(CLUB_MATCHES_PATH)
    print(f"Loading {len(df)} club matches from parquet...")

    # Build lookups
    league_id_map = {
        league.code: league.id
        for league in session.query(League).all()
    }
    team_id_map = {
        team.canonical_name: team.id
        for team in session.query(Team).filter_by(team_type="club").all()
    }

    # Check how many matches already exist
    existing_count = session.query(Match).filter(Match.status == "completed").count()
    if existing_count > 0:
        print(f"  {existing_count} completed matches already exist — skipping bulk insert")
        return

    count = 0
    skipped = 0
    batch = []

    for _, row in df.iterrows():
        raw_code = row["league_code"]
        league_code = LEAGUE_CODE_MAP.get(raw_code)
        if not league_code:
            skipped += 1
            continue

        league_id = league_id_map.get(league_code)
        home_id = team_id_map.get(row["home_team"])
        away_id = team_id_map.get(row["away_team"])

        if not league_id or not home_id or not away_id:
            skipped += 1
            continue

        match_date = row["match_date"]
        if hasattr(match_date, "date"):
            match_date = match_date.date()

        match = Match(
            league_id=league_id,
            season=str(row["season"]) if pd.notna(row.get("season")) else None,
            match_date=match_date,
            home_team_id=home_id,
            away_team_id=away_id,
            home_goals=int(row["home_goals"]) if pd.notna(row["home_goals"]) else None,
            away_goals=int(row["away_goals"]) if pd.notna(row["away_goals"]) else None,
            result=str(row["result"]) if pd.notna(row["result"]) else None,
            ht_home_goals=int(row["ht_home_goals"]) if pd.notna(row.get("ht_home_goals")) else None,
            ht_away_goals=int(row["ht_away_goals"]) if pd.notna(row.get("ht_away_goals")) else None,
            home_shots=int(row["home_shots"]) if pd.notna(row.get("home_shots")) else None,
            away_shots=int(row["away_shots"]) if pd.notna(row.get("away_shots")) else None,
            home_shots_on_target=int(row["home_shots_on_target"]) if pd.notna(row.get("home_shots_on_target")) else None,
            away_shots_on_target=int(row["away_shots_on_target"]) if pd.notna(row.get("away_shots_on_target")) else None,
            home_corners=int(row["home_corners"]) if pd.notna(row.get("home_corners")) else None,
            away_corners=int(row["away_corners"]) if pd.notna(row.get("away_corners")) else None,
            home_fouls=int(row["home_fouls"]) if pd.notna(row.get("home_fouls")) else None,
            away_fouls=int(row["away_fouls"]) if pd.notna(row.get("away_fouls")) else None,
            home_yellow_cards=int(row["home_yellow_cards"]) if pd.notna(row.get("home_yellow_cards")) else None,
            away_yellow_cards=int(row["away_yellow_cards"]) if pd.notna(row.get("away_yellow_cards")) else None,
            home_red_cards=int(row["home_red_cards"]) if pd.notna(row.get("home_red_cards")) else None,
            away_red_cards=int(row["away_red_cards"]) if pd.notna(row.get("away_red_cards")) else None,
            match_importance="league",
            status="completed",
        )
        batch.append(match)
        count += 1

        # Batch insert every 500 rows
        if len(batch) >= 500:
            session.add_all(batch)
            session.flush()
            batch = []
            print(f"  ...inserted {count} matches so far")

    if batch:
        session.add_all(batch)

    session.commit()
    print(f"Seeded {count} completed club matches (skipped {skipped})")


# ── Step 5: Seed upcoming fixtures ────────────────────────────────────────────
def seed_fixtures(session):
    """Load fixtures.parquet and insert scheduled upcoming matches."""
    if not FIXTURES_PATH.exists():
        print(f"WARNING: {FIXTURES_PATH} not found — skipping fixture seed")
        return

    df = pd.read_parquet(FIXTURES_PATH)
    print(f"Loading {len(df)} fixtures from parquet...")

    team_id_map = {
        team.canonical_name: team.id
        for team in session.query(Team).all()
    }

    # Build league_id lookup for resolving fixture league_code
    league_id_map = {
        league.code: league.id
        for league in session.query(League).all()
    }

    count = 0
    skipped = 0

    for _, row in df.iterrows():
        home_name = row["home_team"]
        away_name = row["away_team"]

        # Ensure both teams exist — create them if they don't
        for team_name in (home_name, away_name):
            if team_name not in team_id_map:
                # Alias-aware lookup — see seed_club_teams() for rationale.
                existing = _resolve_team_with_alias(session, team_name)
                if existing:
                    team_id_map[team_name] = existing.id
                else:
                    team = Team(
                        canonical_name=team_name,
                        short_name=team_name[:50],
                        team_type="club",
                    )
                    session.add(team)
                    session.flush()
                    team_id_map[team_name] = team.id

        home_id = team_id_map.get(home_name)
        away_id = team_id_map.get(away_name)

        if not home_id or not away_id:
            skipped += 1
            continue

        # Determine league_id: prefer fixture's own league_code, fall back to home team's league
        league_id = None
        fixture_league_code = row.get("league_code") or row.get("Div")
        if fixture_league_code and fixture_league_code in LEAGUE_CODE_MAP:
            league_code = LEAGUE_CODE_MAP[fixture_league_code]
            league_id = league_id_map.get(league_code)
        elif fixture_league_code and fixture_league_code not in LEAGUE_CODE_MAP:
            # This fixture is from a league we don't cover — skip it
            skipped += 1
            continue

        if league_id is None:
            home_team_obj = session.query(Team).filter_by(id=home_id).first()
            league_id = home_team_obj.league_id if home_team_obj else None

        match_date = row["match_date"]
        if hasattr(match_date, "date"):
            match_date = match_date.date()

        # Check if this fixture already exists (dedup by home_team + away_team + date)
        existing = session.query(Match).filter_by(
            home_team_id=home_id,
            away_team_id=away_id,
            match_date=match_date,
        ).first()
        if existing:
            skipped += 1
            continue

        # Get kickoff time if available
        kickoff_time = None
        if "kickoff_time" in row.index:
            kt = row.get("kickoff_time")
            if pd.notna(kt) and str(kt).strip() and str(kt).strip() != "nan":
                kickoff_time = str(kt).strip()

        match = Match(
            league_id=league_id,
            season="2025-26",
            match_date=match_date,
            home_team_id=home_id,
            away_team_id=away_id,
            kickoff_time=kickoff_time,
            match_importance="league",
            status="scheduled",
        )
        session.add(match)
        count += 1

    session.commit()
    print(f"Seeded {count} upcoming fixtures (skipped {skipped})")


# ── Step 6: Seed FIFA rankings ────────────────────────────────────────────────
def seed_fifa_rankings(session):
    """Load fifa_rankings.parquet and insert ranking data."""
    if not FIFA_RANKINGS_PATH.exists():
        print(f"WARNING: {FIFA_RANKINGS_PATH} not found — skipping FIFA rankings seed")
        return

    df = pd.read_parquet(FIFA_RANKINGS_PATH)
    print(f"Loading {len(df)} FIFA ranking entries from parquet...")

    team_id_map = {
        team.canonical_name: team.id
        for team in session.query(Team).filter_by(team_type="national").all()
    }

    existing_count = session.query(FifaRanking).count()
    if existing_count > 0:
        print(f"  {existing_count} FIFA ranking entries already exist — skipping bulk insert")
        return

    count = 0
    skipped = 0
    batch = []

    for _, row in df.iterrows():
        team_name = row["team"]
        team_id = team_id_map.get(team_name)

        # Only seed rankings for teams we have in our DB (the 48 WC teams)
        if not team_id:
            skipped += 1
            continue

        rank_date = row["rank_date"]
        if hasattr(rank_date, "date"):
            rank_date = rank_date.date()

        ranking = FifaRanking(
            team_id=team_id,
            rank_date=rank_date,
            fifa_rank=int(row["fifa_rank"]),
            total_points=float(row["total_points"]) if pd.notna(row.get("total_points")) else None,
        )
        batch.append(ranking)
        count += 1

        if len(batch) >= 1000:
            session.add_all(batch)
            session.flush()
            batch = []

    if batch:
        session.add_all(batch)

    session.commit()
    print(f"Seeded {count} FIFA ranking entries (skipped {skipped} teams not in DB)")


# ── Main ──────────────────────────────────────────────────────────────────────
def _commit_with_retry(session, step_name: str, max_retries: int = 3) -> bool:
    """Commit with retry on database locked errors. Returns True on success."""
    import time
    for attempt in range(max_retries):
        try:
            session.commit()
            return True
        except Exception as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                print(f"  Database locked during {step_name}, retrying ({attempt + 1}/{max_retries})...")
                session.rollback()
                time.sleep(1)
                continue
            print(f"ERROR: Commit failed during {step_name}: {e}")
            session.rollback()
            return False
    return False


def main():
    print("Creating tables...")
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"ERROR: Failed to create tables: {e}")
        sys.exit(1)

    try:
        with Session() as session:
            steps = [
                ("Step 1: Leagues", seed_leagues),
                ("Step 2: Club teams", seed_club_teams),
                ("Step 3: World Cup national teams", seed_world_cup_teams),
                ("Step 4: Historical club matches", seed_club_matches),
                ("Step 5: Upcoming fixtures", seed_fixtures),
                ("Step 6: FIFA rankings", seed_fifa_rankings),
            ]
            for step_name, step_fn in steps:
                print(f"\n--- {step_name} ---")
                try:
                    step_fn(session)
                except Exception as e:
                    print(f"ERROR in {step_name}: {e}")
                    session.rollback()
                    # Continue to next step rather than aborting entirely
                    continue
    except Exception as e:
        print(f"ERROR: Database session failed: {e}")
        sys.exit(1)

    print("\nSeed complete.")


if __name__ == "__main__":
    main()
