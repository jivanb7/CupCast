"""
backend/api/live.py
====================
Live score endpoints — serves cached live match data.

Endpoints:
  GET /live/scores         — all currently live + recently finished matches
  GET /live/today          — all of today's matches (scheduled, live, finished)
  GET /live/scores/{id}    — single match by Football-Data.org match ID
  POST /live/start         — start live polling (admin only)
  POST /live/stop          — stop live polling (admin only)

The polling service runs in a background thread and caches results in memory.
These endpoints just read from cache — they're instant, no API calls.
"""

from fastapi import APIRouter, Depends, Header, HTTPException

from services.live_score_service import live_scores

router = APIRouter(prefix="/live", tags=["live scores"])


@router.get("/scores")
def get_live_scores():
    """Get all currently live and recently finished matches."""
    return live_scores.get_live()


@router.get("/today")
def get_today_matches():
    """Get all of today's matches across all competitions."""
    return live_scores.get_today()


@router.get("/scores/{match_id}")
def get_live_match(match_id: int):
    """Get a specific live match by Football-Data.org ID."""
    match = live_scores.get_match(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found in live cache")
    return match


def _verify_admin(x_admin_key: str = Header(...)):
    from config import settings
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key


@router.post("/start")
def start_polling(_key: str = Depends(_verify_admin)):
    """Start live score polling (admin only)."""
    from config import settings
    if not settings.football_data_org_api_key:
        raise HTTPException(
            status_code=503,
            detail="FOOTBALL_DATA_ORG_API_KEY not configured in .env"
        )
    live_scores.configure(settings.football_data_org_api_key, poll_interval=10)
    live_scores.start()
    return {"status": "started", "poll_interval": 10}


@router.post("/stop")
def stop_polling(_key: str = Depends(_verify_admin)):
    """Stop live score polling (admin only)."""
    live_scores.stop()
    return {"status": "stopped"}
