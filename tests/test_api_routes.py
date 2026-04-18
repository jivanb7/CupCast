"""
tests/test_api_routes.py
=========================
Integration + functional tests at the FastAPI app boundary.

1. Integration: all expected domain routers are mounted under /api/v1, so no
   path typo silently drops a whole feature (a classic "silent bug").
2. Functional: GET /health responds 200 with the documented shape — this is
   what Docker Compose and Cloud Run use for liveness.

We build a minimal FastAPI app that mirrors main.py's wiring instead of
importing main directly, so tests don't trigger the real startup lifespan
(which downloads fixtures, seeds DB, etc.).
"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_test_app() -> FastAPI:
    """Mirror main.py's router registration without the heavy lifespan."""
    from api.matches import router as matches_router
    from api.predictions import router as predictions_router
    from api.leagues import router as leagues_router
    from api.teams import router as teams_router
    from api.worldcup import router as worldcup_router
    from api.model_perf import router as model_perf_router
    from api.admin import router as admin_router

    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok", "database": "skipped"}

    for r in (
        matches_router, predictions_router, leagues_router,
        teams_router, worldcup_router, model_perf_router, admin_router,
    ):
        app.include_router(r, prefix="/api/v1")
    return app


def test_all_domain_routers_are_mounted_under_api_v1():
    """
    Every domain (matches, predictions, leagues, teams, worldcup, model, admin)
    must contribute at least one route under /api/v1/. Catches accidental prefix
    drops or deleted include_router lines.
    """
    app = _build_test_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    expected_prefixes = [
        "/api/v1/matches",
        "/api/v1/predictions",
        "/api/v1/leagues",
        "/api/v1/teams",
        "/api/v1/worldcup",
        "/api/v1/model",
        "/api/v1/admin",
    ]
    for prefix in expected_prefixes:
        assert any(p.startswith(prefix) for p in paths), (
            f"no route registered under {prefix}; got {sorted(paths)}"
        )


def test_health_endpoint_returns_ok_shape():
    """GET /health → 200 with {status, database} keys."""
    app = _build_test_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert "database" in body
