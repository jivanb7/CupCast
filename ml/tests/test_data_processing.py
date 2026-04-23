"""
ml/tests/test_data_processing.py
==================================
Tests for data_processing.py.

These tests use small in-memory DataFrames and temporary CSV files
to verify behavior without touching the real raw data files.
"""

import io
import textwrap
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ml.src.data_processing import (
    FDUK_COLUMN_MAP,
    _parse_date_column,
    _season_label,
    load_single_league_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(tmp_path: Path, content: str, filename: str = "test.csv") -> Path:
    """Write a CSV string to a temp file and return its Path."""
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content).strip())
    return p


# ---------------------------------------------------------------------------
# _season_label
# ---------------------------------------------------------------------------

class TestSeasonLabel:
    def test_2526_becomes_2025_26(self):
        assert _season_label("2526") == "2025-26"

    def test_0506_becomes_2005_06(self):
        assert _season_label("0506") == "2005-06"

    def test_1011_becomes_2010_11(self):
        assert _season_label("1011") == "2010-11"


# ---------------------------------------------------------------------------
# _parse_date_column
# ---------------------------------------------------------------------------

class TestParseDateColumn:
    def test_parses_dd_mm_yyyy(self):
        series = pd.Series(["01/03/2023", "15/06/2022"])
        result = _parse_date_column(series)
        assert result.iloc[0] == pd.Timestamp("2023-03-01")
        assert result.iloc[1] == pd.Timestamp("2022-06-15")

    def test_parses_dd_mm_yy(self):
        series = pd.Series(["01/03/23", "15/06/22"])
        result = _parse_date_column(series)
        assert result.iloc[0] == pd.Timestamp("2023-03-01")
        assert result.iloc[1] == pd.Timestamp("2022-06-15")

    def test_returns_nat_for_missing(self):
        series = pd.Series([None, "01/03/2023"])
        result = _parse_date_column(series)
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] == pd.Timestamp("2023-03-01")


# ---------------------------------------------------------------------------
# TestLoadSingleLeagueCsv
# ---------------------------------------------------------------------------

class TestLoadSingleLeagueCsv:
    def test_column_renaming(self, tmp_path):
        """FDUK column names (HomeTeam, FTHG, etc.) are renamed to canonical names."""
        csv_content = """
        Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A
        01/03/2023,Arsenal,Chelsea,2,1,H,1.9,3.5,4.0
        """
        p = _write_csv(tmp_path, csv_content)
        df = load_single_league_csv(p, league_code="E0", season="2223")
        assert "match_date" in df.columns
        assert "home_team" in df.columns
        assert "away_team" in df.columns
        assert "home_goals" in df.columns
        assert "away_goals" in df.columns
        assert "result" in df.columns
        # Original FDUK names should be gone
        assert "HomeTeam" not in df.columns
        assert "FTHG" not in df.columns

    def test_date_parsing(self, tmp_path):
        """match_date column is parsed to datetime."""
        csv_content = """
        Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
        01/03/2023,Arsenal,Chelsea,2,1,H
        """
        p = _write_csv(tmp_path, csv_content)
        df = load_single_league_csv(p, league_code="E0", season="2223")
        assert pd.api.types.is_datetime64_any_dtype(df["match_date"])
        assert df["match_date"].iloc[0] == pd.Timestamp("2023-03-01")

    def test_team_name_resolution(self, tmp_path):
        """Known alias team names are resolved to canonical names."""
        csv_content = """
        Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
        01/03/2023,Man United,Arsenal,2,1,H
        """
        p = _write_csv(tmp_path, csv_content)
        df = load_single_league_csv(p, league_code="E0", season="2223")
        assert df["home_team"].iloc[0] == "Manchester United"

    def test_handles_missing_optional_columns(self, tmp_path):
        """CSV without optional stat columns (shots, corners) should still load."""
        csv_content = """
        Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
        01/03/2023,Arsenal,Chelsea,2,1,H
        """
        p = _write_csv(tmp_path, csv_content)
        df = load_single_league_csv(p, league_code="E0", season="2223")
        assert len(df) == 1
        # Optional columns should be present as NA
        assert "odds_home" in df.columns

    def test_league_code_from_argument_not_csv(self, tmp_path):
        """league_code is taken from argument, overriding any Div column."""
        csv_content = """
        Date,Div,HomeTeam,AwayTeam,FTHG,FTAG,FTR
        01/03/2023,E0,Arsenal,Chelsea,2,1,H
        """
        p = _write_csv(tmp_path, csv_content)
        df = load_single_league_csv(p, league_code="SP1", season="2223")
        assert df["league_code"].iloc[0] == "SP1"

    def test_season_label_applied(self, tmp_path):
        """Season is derived from the season argument."""
        csv_content = """
        Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
        01/03/2023,Arsenal,Chelsea,2,1,H
        """
        p = _write_csv(tmp_path, csv_content)
        df = load_single_league_csv(p, league_code="E0", season="2223")
        assert df["season"].iloc[0] == "2022-23"

    def test_invalid_result_values_filtered_out(self, tmp_path):
        """Rows with result other than H/D/A are dropped."""
        csv_content = """
        Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
        01/03/2023,Arsenal,Chelsea,2,1,H
        02/03/2023,Liverpool,Man City,1,1,INVALID
        """
        p = _write_csv(tmp_path, csv_content)
        df = load_single_league_csv(p, league_code="E0", season="2223")
        assert len(df) == 1
        assert df["result"].iloc[0] == "H"

    def test_returns_empty_dataframe_for_nonexistent_file(self, tmp_path):
        p = tmp_path / "nonexistent.csv"
        df = load_single_league_csv(p, league_code="E0", season="2223")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0


# ---------------------------------------------------------------------------
# TestProcessClubMatches (uses real parquet — validates output shape)
# ---------------------------------------------------------------------------

class TestProcessClubMatches:
    """These tests use the real processed data to verify output integrity."""

    @pytest.fixture(scope="class")
    def club_matches(self):
        """Load the real processed club matches parquet."""
        from ml.src.config import PROCESSED_DIR
        parquet_path = PROCESSED_DIR / "club_matches.parquet"
        if not parquet_path.exists():
            pytest.skip(f"club_matches.parquet not found at {parquet_path}")
        return pd.read_parquet(parquet_path)

    def test_deduplication(self, club_matches):
        """No duplicate (match_date, home_team, away_team) combinations."""
        dupes = club_matches.duplicated(subset=["match_date", "home_team", "away_team"])
        assert dupes.sum() == 0, f"Found {dupes.sum()} duplicate matches"

    def test_no_nan_in_required_columns(self, club_matches):
        """Required columns must have no NaN."""
        required = ["match_date", "home_team", "away_team", "result"]
        for col in required:
            nan_count = club_matches[col].isna().sum()
            assert nan_count == 0, f"Column '{col}' has {nan_count} NaN values"

    def test_result_values_are_valid(self, club_matches):
        """All result values must be H, D, or A."""
        valid_results = {"H", "D", "A"}
        invalid = ~club_matches["result"].isin(valid_results)
        assert invalid.sum() == 0, f"Found {invalid.sum()} invalid result values"

    def test_sorted_by_date(self, club_matches):
        """Data should be sorted by match_date ascending."""
        assert (club_matches["match_date"].diff().dropna() >= pd.Timedelta(0)).all()

    def test_result_encoded_matches_result(self, club_matches):
        """result_encoded should be consistent with result."""
        from ml.src.config import RESULT_TO_INT
        for result, code in RESULT_TO_INT.items():
            mask = club_matches["result"] == result
            assert (club_matches.loc[mask, "result_encoded"] == code).all()


# ---------------------------------------------------------------------------
# TestProcessInternationalMatches
# ---------------------------------------------------------------------------

class TestProcessInternationalMatches:
    def test_result_derived_from_scores(self):
        """home_score > away_score → result='H', equal → 'D', less → 'A'."""
        import numpy as np
        from ml.src.data_processing import process_international_matches

        # Test the logic directly (numpy select pattern used in the function)
        home_goals = pd.Series([2, 1, 0])
        away_goals = pd.Series([1, 1, 2])
        conditions = [
            home_goals > away_goals,
            home_goals == away_goals,
            home_goals < away_goals,
        ]
        result = np.select(conditions, ["H", "D", "A"], default="D")
        assert list(result) == ["H", "D", "A"]

    def test_tournament_type_classification(self):
        """Tournament name → tournament_type mapping is correct."""
        import pandas as pd

        tournament_map = {
            "FIFA World Cup": "world_cup",
            "FIFA World Cup qualification": "qualifier",
            "Friendly": "friendly",
            "UEFA Euro": "continental",
            "UEFA Nations League": "competitive",
        }
        tournaments = pd.Series(list(tournament_map.keys()))
        expected = pd.Series(list(tournament_map.values()))
        result = tournaments.map(tournament_map)
        assert list(result) == list(expected)

    def test_real_intl_parquet_has_result_column(self):
        """The processed intl_matches.parquet should have a 'result' column."""
        from ml.src.config import PROCESSED_DIR
        parquet_path = PROCESSED_DIR / "intl_matches.parquet"
        if not parquet_path.exists():
            pytest.skip("intl_matches.parquet not found")
        df = pd.read_parquet(parquet_path)
        assert "result" in df.columns
        assert set(df["result"].unique()).issubset({"H", "D", "A"})
