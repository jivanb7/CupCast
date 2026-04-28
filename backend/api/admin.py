"""
backend/api/admin.py
=====================
Internal/admin endpoints for triggering pipeline operations.

ALL endpoints in this router require the ADMIN_API_KEY header:
  X-Admin-Key: <value from ADMIN_API_KEY env var>

Return 403 Forbidden if key is missing or incorrect.

Endpoints:
  POST /admin/data/refresh
    Triggers: ML data ingestion + processing + feature engineering
    Returns: {"status": "started"} (fires background task)

  POST /admin/model/retrain
    Query params: model_type ('club' | 'intl' | 'both', default 'both')
    Triggers: Model training pipeline
    Returns: {"status": "started"}

  POST /admin/predictions/generate
    Triggers: Load production model, run inference on upcoming matches, store
    Returns: {"status": "done", "predictions_generated": N}

Security note:
  Protected by a static API key for MVP. In production, these should
  be triggered by GitHub Actions using a secrets-stored key, never exposed to
  the public internet.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


# Health endpoint thresholds. Mirror the anomaly thresholds in
# revalidate_recent_scores.py so the Cloud Logging WARNING/ERROR levels and
# this endpoint's status field tell the same story.
_HEALTH_OK_CORRECTIONS_24H = 5
_HEALTH_WARN_CORRECTIONS_24H = 15
_HEALTH_OK_REVAL_AGE_HOURS = 12
_HEALTH_ERROR_REVAL_AGE_HOURS = 24
# Window after a match's updated_at was last touched, beyond which a
# 'completed' match is considered stale w.r.t. cross-source confirmation.
_STALE_COMPLETED_WINDOW_HOURS = 6


def verify_admin_key(x_admin_key: str = Header(...)):
    """FastAPI dependency: verify the admin API key header."""
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key


@router.get("/health/scores")
def scores_health(db: Session = Depends(get_db)):
    """Read-only system status for the score-validation pipeline.

    No auth: this endpoint is bookmark-friendly so anyone (incl. uptime
    monitors) can poll it. It returns counts and timestamps only — no PII,
    no scores, no model output.

    Status semantics (mirror revalidate's anomaly log thresholds):
      ok    : corrections_24h <= 5 AND last revalidation <= 12 h ago
      warn  : 5 < corrections_24h <= 15 OR last revalidation > 12 h ago
      error : corrections_24h > 15 OR last revalidation > 24 h ago OR no data
    """
    from models.match import Match
    from models.score_correction import ScoreCorrection

    now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)
    cutoff_24h = now_naive - timedelta(hours=24)
    cutoff_7d = now_naive - timedelta(days=7)
    stale_cutoff = now_naive - timedelta(hours=_STALE_COMPLETED_WINDOW_HOURS)

    corrections_24h = (
        db.query(func.count(ScoreCorrection.id))
        .filter(ScoreCorrection.corrected_at >= cutoff_24h)
        .scalar()
        or 0
    )
    corrections_7d = (
        db.query(func.count(ScoreCorrection.id))
        .filter(ScoreCorrection.corrected_at >= cutoff_7d)
        .scalar()
        or 0
    )

    # "Last revalidation" = the most recent run_id that came from the
    # standalone revalidate script (run_ids from score_updater are prefixed
    # so we can distinguish them — but BOTH count toward "the system saw
    # data in the last N hours"). We surface the most recent ScoreCorrection
    # timestamp as a proxy for "did the pipeline run". This is intentionally
    # approximate: a clean run with zero mismatches won't show here, which
    # is why the heuristic also looks at corrections_24h.
    last_correction = (
        db.query(ScoreCorrection)
        .order_by(ScoreCorrection.corrected_at.desc())
        .first()
    )
    if last_correction is not None:
        # Group by run_id to summarize the most recent run
        last_run_id = last_correction.run_id
        run_rows = (
            db.query(ScoreCorrection)
            .filter(ScoreCorrection.run_id == last_run_id)
            .all()
        )
        last_revalidation = {
            "run_at": last_correction.corrected_at.isoformat(),
            "run_id": last_run_id,
            "mismatches_found": len(run_rows),
            "predictions_reevaluated": sum(
                (r.predictions_reevaluated or 0) for r in run_rows
            ),
        }
        revalidation_age_hours = (
            now_naive - last_correction.corrected_at
        ).total_seconds() / 3600
    else:
        last_revalidation = None
        revalidation_age_hours = None

    # Stale completed matches: status='completed' but updated_at older than
    # the 6-hour cross-source confirmation window. NULL updated_at counts as
    # stale (legacy rows the pipeline has never re-touched).
    stale_completed = (
        db.query(func.count(Match.id))
        .filter(
            Match.status == "completed",
            (Match.updated_at == None) | (Match.updated_at < stale_cutoff),  # noqa: E711
        )
        .scalar()
        or 0
    )

    # Apply the status heuristic. Order matters: error overrides warn.
    if (
        corrections_24h > _HEALTH_WARN_CORRECTIONS_24H
        or revalidation_age_hours is None
        or (revalidation_age_hours is not None and revalidation_age_hours > _HEALTH_ERROR_REVAL_AGE_HOURS)
    ):
        status = "error"
    elif (
        corrections_24h > _HEALTH_OK_CORRECTIONS_24H
        or (revalidation_age_hours is not None and revalidation_age_hours > _HEALTH_OK_REVAL_AGE_HOURS)
    ):
        status = "warn"
    else:
        status = "ok"

    return {
        "status": status,
        "last_revalidation": last_revalidation,
        "corrections_last_24h": int(corrections_24h),
        "corrections_last_7d": int(corrections_7d),
        "stale_completed_matches": int(stale_completed),
        "checked_at": now.isoformat(),
    }


@router.post("/scores/update")
def update_scores(
    espn_only: bool = Query(
        False,
        description=(
            "When true, run only the ESPN scoreboard pass. ESPN is keyless and "
            "quota-free, so this endpoint can safely be cron'd every 5 min to "
            "close the gap between match end and the user seeing the final score. "
            "The full pass (CSV + Football-Data.org) still runs on its 2-hour cron."
        ),
    ),
    days_back: int = Query(
        1,
        ge=0,
        le=14,
        description=(
            "How many prior days the ESPN pass should also scan with ?dates="
            "YYYYMMDD. Default 1 = today + yesterday — catches matches that "
            "ended after the previous tick and any same-day update we missed. "
            "Set higher (up to 14) for a one-shot backfill of stuck older "
            "matches; this only affects the ESPN pass."
        ),
    ),
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Fetch latest scores and update match results.

    Default: full pass (ESPN [today + yesterday] + football-data.co.uk CSV +
    Football-Data.org API). With ?espn_only=true: ESPN pass only (~10 s,
    no third-party quota).
    """
    if espn_only:
        from services.score_updater import update_scores_from_espn

        try:
            stats = update_scores_from_espn(db, days_back=days_back)
            return {"status": "done", "mode": "espn_only", "days_back": days_back, **stats}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"ESPN score update failed: {str(e)}")

    from services.score_updater import update_scores as do_update

    try:
        stats = do_update(db)
        return {"status": "done", "mode": "full", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Score update failed: {str(e)}")


@router.post("/scores/live-sync")
def live_sync(_key: str = Depends(verify_admin_key)):
    """One-shot live-score poll + DB sync.

    Cron'd every minute by Cloud Scheduler so in-progress matches show
    status='live', the current minute, and the running score on the
    frontend (the existing pre-match prediction card flips into a live
    card the moment status='live' lands in the DB).

    Calls ESPN (no key, no quota) and Football-Data.org (10 req/min) into
    the live_scores singleton's in-memory cache, then runs _sync_to_db()
    which writes home_goals/away_goals + status='live' for matches in
    play and finalises any stale 'live' rows that ended without a
    FINISHED signal. Idempotent — repeated calls on unchanged scores
    are no-ops.
    """
    from services.live_score_service import live_scores

    import logging
    log = logging.getLogger(__name__)

    try:
        # Populate cache from both sources (FD.org + ESPN). Both are
        # safe to call sequentially; total work ≈ 1.5 s.
        try:
            live_scores._do_poll()  # FD.org — quota-bounded, no-op if no key
        except Exception as exc:
            log.warning("live-sync: FD.org poll failed: %s", exc)
        try:
            live_scores._do_poll_espn()  # ESPN — keyless, no quota
        except Exception as exc:
            log.warning("live-sync: ESPN poll failed: %s", exc)

        # Now write whatever's in cache to the DB (status='live' + scores
        # + minute for in-play games; finalise stale 'live' rows that
        # the cache no longer sees).
        live_scores._sync_to_db()

        cache_size = len(live_scores._cache)
        live_count = sum(
            1 for m in live_scores._cache.values()
            if m.get("status") in ("IN_PLAY", "HALFTIME", "PAUSED")
        )
        return {
            "status": "done",
            "cache_size": cache_size,
            "in_play": live_count,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Live sync failed: {exc}")


@router.post("/scores/revalidate")
def revalidate_scores(
    days: int = Query(2, ge=1, le=7),
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Cross-check the last N days of completed match scores against API-Football.

    Catches the "intermediate score frozen" failure mode that the CSV-based
    score_updater can leave behind (e.g. Real Betis 0-1 instead of 1-1 final
    on 2026-04-24). For any DB completed match whose API-Football full-time
    score disagrees with ours, the row is rewritten and predictions on it are
    re-evaluated.

    Recommended Cloud Scheduler cron: every 6 h
      e.g.  0 */6 * * *   POST /admin/scores/revalidate?days=2
    """
    from scripts.revalidate_recent_scores import revalidate

    try:
        return {"status": "done", **revalidate(db, days=days)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Score revalidation failed: {str(e)}"
        )


@router.post("/data/refresh")
def refresh_data(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Trigger data ingestion and processing pipeline as a background task."""
    from services.data_service import trigger_data_refresh

    background_tasks.add_task(trigger_data_refresh)
    return {"status": "started", "message": "Data refresh pipeline started in background"}


@router.post("/model/retrain")
def retrain_model(
    background_tasks: BackgroundTasks,
    model_type: str = "both",
    _key: str = Depends(verify_admin_key),
):
    """Trigger model retraining for one or both model types."""
    from services.data_service import trigger_retrain

    valid_types = ("club", "intl", "both")
    if model_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid model_type '{model_type}'. Must be one of {valid_types}",
        )

    background_tasks.add_task(trigger_retrain, model_type)
    return {"status": "started", "model_type": model_type, "message": "Retraining started"}


@router.post("/predictions/generate")
def generate_predictions(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Run batch inference on upcoming matches and store predictions."""
    from services.prediction_service import generate_batch_predictions

    try:
        n = generate_batch_predictions(db)
        return {"status": "done", "predictions_generated": n}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction generation failed: {str(e)}")


@router.post("/fixtures/seed")
def seed_fixtures(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Fetch upcoming fixtures from Football-Data.org + fixtures.csv and seed into DB."""
    from services.fixture_seeder import seed_all_fixtures

    try:
        stats = seed_all_fixtures(db)
        return {"status": "done", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fixture seeding failed: {str(e)}")


@router.post("/players/refresh")
def refresh_all_players(
    background_tasks: BackgroundTasks,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Refresh top scorers and injuries for all leagues.

    Fetches /players/topscorers and /injuries from API-Football for each of
    the 10 tracked leagues (~20 API calls total). Runs synchronously and returns
    counts when complete.
    """
    from services.player_availability_service import refresh_all_leagues

    try:
        result = refresh_all_leagues(db)
        return {"status": "done", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Player refresh failed: {str(e)}")


@router.post("/odds/refresh")
def refresh_all_odds(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Refresh bookmaker odds + value-pick flags for upcoming matches in all leagues.

    Fetches /fixtures + /odds from API-Football for each league, matches fixtures
    to DB matches, and upserts odds_home/draw/away + recomputed edges onto every
    Prediction row. Runs synchronously and returns counts.

    API cost: ~5 calls per league (1 fixtures + ~4 odds pages) = ~50 calls total.

    Expected schedule (Cloud Scheduler, both UTC):
      - 07:30 daily — after prediction refresh at 07:00
      - 15:00 daily — mid-day top-up for late-priced matches
    """
    from services.odds_service import refresh_all_leagues_odds

    try:
        result = refresh_all_leagues_odds(db)
        return {"status": "done", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Odds refresh failed: {str(e)}")


@router.post("/odds/refresh/{league_code}")
def refresh_league_odds(
    league_code: str,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Refresh odds + value-pick flags for a single league."""
    from services.odds_service import refresh_odds_for_league
    from services.player_availability_service import LEAGUE_API_FOOTBALL_IDS

    if league_code not in LEAGUE_API_FOOTBALL_IDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown league_code '{league_code}'. "
                f"Must be one of: {sorted(LEAGUE_API_FOOTBALL_IDS.keys())}"
            ),
        )

    try:
        stats = refresh_odds_for_league(db, league_code)
        return {"status": "done", **stats}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Odds refresh failed for '{league_code}': {str(e)}",
        )


@router.post("/world-cup/run-simulation")
def run_wc_simulation(
    n_sims: int = 10_000,
    seed: int = 42,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Run a fresh World Cup Monte Carlo simulation and persist the result.

    Query params:
      n_sims: number of MC runs (default 10k — ~3-4s on a laptop).
      seed:   master RNG seed for reproducibility.

    Returns: row id, top-5 contenders, runtime, and sum-to-100 sanity check.
    """
    import json
    import time

    from models.tournament_simulation import TournamentSimulation
    from services.tournament_simulator import result_to_json, simulate_world_cup

    if n_sims < 1 or n_sims > 100_000:
        raise HTTPException(
            status_code=422,
            detail=f"n_sims must be in [1, 100000], got {n_sims}",
        )

    started = time.perf_counter()
    try:
        result = simulate_world_cup(db, n_sims=n_sims, seed=seed)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}")
    elapsed = time.perf_counter() - started

    payload = result_to_json(result)
    row = TournamentSimulation(
        run_at=result.run_at,
        n_sims=result.n_sims,
        result_json=json.dumps(payload),
        model_version=result.model_version,
        elo_model_version=result.elo_model_version,
        seed=result.seed,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    sum_pct = sum(p.win_tournament_pct for p in result.per_team)

    return {
        "status": "done",
        "simulation_id": row.id,
        "run_at": result.run_at.isoformat(),
        "n_sims": result.n_sims,
        "seed": result.seed,
        "runtime_seconds": round(elapsed, 3),
        "sum_win_tournament_pct": round(sum_pct, 4),
        "top_5_contenders": [
            {
                "name": p.name,
                "country_code": p.country_code,
                "win_tournament_pct": round(p.win_tournament_pct, 2),
            }
            for p in result.per_team[:5]
        ],
    }


@router.post("/players/refresh/{league_code}")
def refresh_league_players(
    league_code: str,
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Refresh top scorers and injuries for a specific league.

    Args:
        league_code: One of the tracked league codes, e.g. 'epl', 'ucl', 'laliga'.
    """
    from services.player_availability_service import (
        LEAGUE_API_FOOTBALL_IDS,
        refresh_injuries,
        refresh_top_scorers,
    )

    if league_code not in LEAGUE_API_FOOTBALL_IDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown league_code '{league_code}'. "
                f"Must be one of: {sorted(LEAGUE_API_FOOTBALL_IDS.keys())}"
            ),
        )

    try:
        scorers = refresh_top_scorers(db, league_code)
        injuries = refresh_injuries(db, league_code)
        return {
            "status": "done",
            "league": league_code,
            "scorers_updated": scorers,
            "injuries_updated": injuries,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Player refresh failed for '{league_code}': {str(e)}",
        )


@router.post("/fixtures/cleanup-ucl-phantoms")
def cleanup_ucl_phantoms(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Remove UCL fixtures that involve clubs which don't actually play in
    the Champions League proper.

    Background: API-Football's UCL feed occasionally includes preliminary /
    qualifying-round fixtures for clubs from smaller leagues (e.g. Drita
    from Kosovo, Inter Club d'Escaldes from Andorra). When those land in
    our `ucl` league_code with kickoff times overlapping the real semifinal
    legs, the slate ends up showing 8 cards where there should be 4. This
    endpoint deletes any UCL matches whose home OR away team is on the
    blocklist below, plus their predictions and any score_corrections rows.

    Add a team to the blocklist when the user reports a phantom; keep the
    list explicit so we never delete a legitimate fixture by accident.
    """
    from models.league import League
    from models.match import Match
    from models.prediction import Prediction
    from models.team import Team

    # Source of truth lives in services/ucl_fixture_service so the parse-
    # time filter, the seed sweep, and this admin endpoint stay aligned.
    from services.ucl_fixture_service import UCL_PHANTOM_BLOCKLIST as BLOCKLIST_NAMES

    ucl = db.query(League).filter(League.code == "ucl").first()
    if not ucl:
        raise HTTPException(status_code=404, detail="UCL league row not found")

    bad_teams = (
        db.query(Team).filter(Team.canonical_name.in_(BLOCKLIST_NAMES)).all()
    )
    bad_team_ids = {t.id for t in bad_teams}
    if not bad_team_ids:
        return {"status": "done", "deleted_matches": 0, "deleted_predictions": 0, "blocked": []}

    phantom_matches = (
        db.query(Match)
        .filter(
            Match.league_id == ucl.id,
            (Match.home_team_id.in_(bad_team_ids)) | (Match.away_team_id.in_(bad_team_ids)),
        )
        .all()
    )
    phantom_match_ids = [m.id for m in phantom_matches]

    deleted_preds = 0
    if phantom_match_ids:
        deleted_preds = (
            db.query(Prediction)
            .filter(Prediction.match_id.in_(phantom_match_ids))
            .delete(synchronize_session=False)
        )
        # score_corrections may reference these matches too — defensive cleanup
        try:
            from sqlalchemy import text
            db.execute(
                text("DELETE FROM score_corrections WHERE match_id = ANY(:ids)"),
                {"ids": phantom_match_ids},
            )
        except Exception:
            # SQLite uses different syntax; ignore (cleanup is best-effort).
            pass

    for m in phantom_matches:
        db.delete(m)

    db.commit()

    return {
        "status": "done",
        "deleted_matches": len(phantom_match_ids),
        "deleted_predictions": deleted_preds,
        "blocked": sorted(BLOCKLIST_NAMES),
        "match_ids": phantom_match_ids,
    }


@router.post("/teams/audit-crests")
def audit_team_crests(
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Apply curated corrections to ``Team.logo_url`` for known-wrong crests.

    Background: the fixture seeder occasionally pulls a wrong API-Football
    team id when there's a name collision (e.g. PSG was bound to api id 3408,
    which is actually Aris Limassol of Cyprus). The frontend then renders the
    wrong club crest. Maintaining a tiny curated map here is safer than
    re-resolving every team — these fixes are stable, documented, and easy to
    review in PRs.

    Each entry maps the canonical team name to the correct api-sports.io
    image id. We match on ``canonical_name`` and rewrite ``logo_url`` only
    when the current value differs.
    """
    from models.team import Team

    CRESTS = {
        # Big clubs whose API-Football id collided with another team during
        # seeding and need a one-time correction. Add new entries here when
        # users report a wrong crest — keep the list short and intentional.
        "Paris Saint-Germain": 85,
    }
    base = "https://media.api-sports.io/football/teams"
    fixed = []
    skipped = []
    for name, api_id in CRESTS.items():
        team = db.query(Team).filter(Team.canonical_name == name).first()
        if not team:
            skipped.append({"name": name, "reason": "team not found"})
            continue
        target = f"{base}/{api_id}.png"
        if team.logo_url == target:
            skipped.append({"name": name, "reason": "already correct"})
            continue
        old = team.logo_url
        team.logo_url = target
        fixed.append({"name": name, "team_id": team.id, "old": old, "new": target})

    if fixed:
        db.commit()

    return {"status": "done", "fixed": fixed, "skipped": skipped}


@router.post("/matches/cleanup-bogus-finalized")
def cleanup_bogus_finalized(
    days_back: int = Query(60, ge=1, le=365),
    dry_run: bool = Query(False),
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Revert matches that were prematurely finalized with hallmark bogus scores.

    Targets three classes of corrupt rows (within the ``days_back`` window):
      - Null-kickoff 0-0 completed  (primary hallmark — placeholder never played)
      - Future date + completed     (logically impossible)
      - Null-kickoff completed, any score (broader suspect set)

    For each match found:
      - Sets status='scheduled', home_goals=NULL, away_goals=NULL, result=NULL
      - Sets was_correct=NULL on every linked Prediction row so they are no
        longer counted toward rolling accuracy until the match grades correctly.

    All writes happen in a single transaction; any error triggers a full rollback.
    Pass ``dry_run=true`` to see what WOULD be reverted without writing anything.
    """
    from models.league import League
    from models.match import Match
    from models.prediction import Prediction
    from models.team import Team

    today = datetime.now(timezone.utc).date()
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = today - timedelta(days=days_back)

    # Gather all three classes.  Use a set to deduplicate (Class A ⊆ Class C).
    suspect_ids: set[int] = set()

    # Class A: null-kickoff 0-0 completed within window
    class_a = (
        db.query(Match)
        .filter(
            Match.status == "completed",
            Match.kickoff_time == None,  # noqa: E711
            Match.home_goals == 0,
            Match.away_goals == 0,
            Match.match_date >= cutoff,
        )
        .all()
    )
    for m in class_a:
        suspect_ids.add(m.id)

    # Class B: future date + completed (no date window needed — always wrong)
    class_b = (
        db.query(Match)
        .filter(
            Match.status == "completed",
            Match.match_date > today,
        )
        .all()
    )
    for m in class_b:
        suspect_ids.add(m.id)

    # Class C: null-kickoff completed within window (any score — superset of A)
    class_c = (
        db.query(Match)
        .filter(
            Match.status == "completed",
            Match.kickoff_time == None,  # noqa: E711
            Match.match_date >= cutoff,
        )
        .all()
    )
    for m in class_c:
        suspect_ids.add(m.id)

    if not suspect_ids:
        return {
            "status": "done",
            "matches_reverted": 0,
            "predictions_uncorrected": 0,
            "dry_run": dry_run,
            "matches": [],
        }

    # Fetch all suspect matches in one query for the response payload and writes.
    suspect_matches = (
        db.query(Match)
        .filter(Match.id.in_(suspect_ids))
        .all()
    )

    # Build team + league caches to avoid N+1 in the response payload.
    team_ids = {m.home_team_id for m in suspect_matches} | {m.away_team_id for m in suspect_matches}
    league_ids = {m.league_id for m in suspect_matches}
    teams_by_id = {t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()}
    leagues_by_id = {lg.id: lg for lg in db.query(League).filter(League.id.in_(league_ids)).all()}

    def _tname(tid):
        t = teams_by_id.get(tid)
        return t.canonical_name if t else f"team#{tid}"

    def _lcode(lid):
        lg = leagues_by_id.get(lid)
        return lg.code if lg else f"league#{lid}"

    match_summaries = [
        {
            "match_id": m.id,
            "home_team": _tname(m.home_team_id),
            "away_team": _tname(m.away_team_id),
            "league_code": _lcode(m.league_id),
            "match_date": m.match_date.isoformat() if m.match_date else None,
            "score_before": f"{m.home_goals}-{m.away_goals}",
            "result_before": m.result,
        }
        for m in suspect_matches
    ]

    # Count predictions that will be un-corrected.
    predictions_to_clear = (
        db.query(Prediction)
        .filter(Prediction.match_id.in_(suspect_ids))
        .all()
    )
    predictions_count = len(predictions_to_clear)

    if dry_run:
        return {
            "status": "done",
            "matches_reverted": len(suspect_matches),
            "predictions_uncorrected": predictions_count,
            "dry_run": True,
            "matches": match_summaries,
        }

    # Apply within a single transaction — rollback on any error.
    try:
        for m in suspect_matches:
            m.status = "scheduled"
            m.home_goals = None
            m.away_goals = None
            m.result = None
            m.updated_at = now_naive

        for pred in predictions_to_clear:
            pred.was_correct = None

        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Cleanup transaction failed and was rolled back: {exc}",
        )

    return {
        "status": "done",
        "matches_reverted": len(suspect_matches),
        "predictions_uncorrected": predictions_count,
        "dry_run": False,
        "matches": match_summaries,
    }


@router.post("/explanations/backfill")
def backfill_explanations(
    limit: int = Query(2000, ge=1, le=20000),
    overwrite: bool = Query(False),
    _key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Populate ``Prediction.explanation_text`` for rows that don't have one.

    By default only fills rows where ``explanation_text IS NULL``. Pass
    ``overwrite=true`` to rewrite every row in the batch — useful when
    template changes ship and we want the persisted text refreshed.

    ``limit`` caps the batch so we can run this incrementally against the
    65k+ existing predictions without one giant transaction.
    """
    from types import SimpleNamespace

    from models.league import League
    from models.match import Match
    from models.prediction import Prediction
    from models.team import Team
    from services.reasoning import generate_explanation, template_count

    # Inner-join to Match so orphan predictions (FK doesn't resolve, e.g.
    # leftover from prod dedup that didn't replay locally) are skipped
    # cleanly instead of churning through every batch.
    q = db.query(Prediction).join(Match, Prediction.match_id == Match.id)
    if not overwrite:
        q = q.filter(Prediction.explanation_text.is_(None))
    preds = q.order_by(Prediction.id.desc()).limit(limit).all()
    if not preds:
        remaining_now = db.query(Prediction).filter(Prediction.explanation_text.is_(None)).count()
        return {
            "status": "done",
            "templates_in_pool": template_count(),
            "scanned": 0,
            "written": 0,
            "skipped_no_template_fired": 0,
            "failed": 0,
            "remaining_null": remaining_now,
            "overwrite": overwrite,
        }

    # Batch-load matches + their teams + leagues so the loop is N+0 not N+3.
    match_ids = {p.match_id for p in preds}
    matches = db.query(Match).filter(Match.id.in_(match_ids)).all()
    by_match_id = {m.id: m for m in matches}
    team_ids = {m.home_team_id for m in matches} | {m.away_team_id for m in matches}
    league_ids = {m.league_id for m in matches}
    teams = {t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()}
    leagues = {l.id: l for l in db.query(League).filter(League.id.in_(league_ids)).all()}

    def _shim(match):
        if match is None:
            return None
        return SimpleNamespace(
            id=match.id,
            home_team=teams.get(match.home_team_id),
            away_team=teams.get(match.away_team_id),
            league=leagues.get(match.league_id),
            stage=match.stage,
            status=match.status,
        )

    written = 0
    skipped = 0
    failed = 0
    for pred in preds:
        match = by_match_id.get(pred.match_id)
        try:
            text = generate_explanation(pred, _shim(match))
        except Exception:
            failed += 1
            continue
        if not text:
            skipped += 1
            continue
        pred.explanation_text = text
        written += 1

    if written:
        db.commit()
    else:
        db.rollback()

    remaining = db.query(Prediction).filter(Prediction.explanation_text.is_(None)).count()
    return {
        "status": "done",
        "templates_in_pool": template_count(),
        "scanned": len(preds),
        "written": written,
        "skipped_no_template_fired": skipped,
        "failed": failed,
        "remaining_null": remaining,
        "overwrite": overwrite,
    }
