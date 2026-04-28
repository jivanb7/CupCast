# SQLAlchemy ORM models
# Import all models here so Alembic autogenerate can discover them
from models.league import League
from models.team import Team, TeamNameAlias
from models.match import Match
from models.prediction import Prediction
from models.fifa_ranking import FifaRanking
from models.model_registry import ModelRegistry
from models.player import Player
from models.player_injury import PlayerInjury
from models.team_elo import TeamElo
from models.tournament_simulation import TournamentSimulation
from models.score_correction import ScoreCorrection
from models.api_football_prediction import APIFootballPrediction
