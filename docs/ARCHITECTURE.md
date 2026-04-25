---
date: 2026-04-24
type: architecture
tags: [cupcast, architecture, system-design]
---

# CupCast Architecture

> [!info] What CupCast is
> ML-driven football match predictor + World Cup 2026 hub. Consumes football fixtures from multiple data feeds, runs predictions through routed ML models, surfaces value picks (model probability vs bookmaker implied probability), and projects World Cup outcomes via Monte Carlo simulation over an Elo-based base predictor.

## Stack at a glance

| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite + Tailwind, hosted on Cloud Run (Nginx container) |
| Backend | FastAPI + SQLAlchemy + Alembic, hosted on Cloud Run |
| DB | Supabase Postgres (managed) |
| ML registry | MLflow on GCP VM, fronted by Caddy with basic auth |
| Model artifacts | GCS bucket |
| Job scheduling | Cloud Scheduler → POST `/api/v1/admin/*` endpoints |
| CI/CD | GitHub Actions (CI on every push, Deploy on push to main) |

## Data flow

```
            ┌─────────────────────────────────────────────────┐
            │          External data sources                  │
            ├─────────────────────────────────────────────────┤
            │  football-data.org   ESPN   API-Football         │
            │  (fixtures + scores) (live) (odds + logos +     │
            │                            cross-source check)  │
            └────────┬────────────┬────────────┬───────────────┘
                     │            │            │
                     ▼            ▼            ▼
              ┌────────────────────────────────────┐
              │  Backend services (Cloud Run)      │
              │  - fixture_seeder                  │
              │  - score_updater (+ live API)      │
              │  - odds_service                    │
              │  - prediction_service (routes by   │
              │    league)                         │
              │  - tournament_simulator (WC)       │
              │  - revalidate_recent_scores        │
              │    (cross-source safety net)       │
              └────────────┬───────────────────────┘
                           │
                           ▼
                ┌──────────────────────┐         ┌──────────────────┐
                │  Supabase Postgres   │◀───────▶│  MLflow registry │
                │  matches             │  load   │  (3 models)      │
                │  teams               │  models │  cupcast-club    │
                │  predictions         │         │  cupcast-club-   │
                │  team_elo            │         │    top5          │
                │  tournament_         │         │  cupcast-intl    │
                │    simulations       │         └──────────────────┘
                │  score_corrections   │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │  Backend API         │
                │  /api/v1/matches     │
                │  /api/v1/world-cup   │
                │  /api/v1/predictions │
                │  /api/v1/admin       │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │  Frontend (Cloud Run)│
                │  /                   │
                │  /matches            │
                │  /match/:id          │
                │  /world-cup          │
                │  /model-performance  │
                │  /about              │
                └──────────────────────┘
```

## Prediction routing

> [!important] Different leagues use different predictors
> League → model mapping happens in `backend/services/prediction_service.py`.

| League code | Model | Where loaded |
|---|---|---|
| `epl, championship, league_one, league_two, national_league` | `cupcast-club-top5-model` (XGB + isotonic calibration) | MLflow `@prod` alias |
| `laliga, seriea, bundesliga, ligue1, ucl` | `cupcast-club-top5-model` | MLflow `@prod` alias |
| `worldcup` | **Elo predictor** (`backend/services/national_elo.py`) — pure Python | Local module (no MLflow round-trip) |
| `mls` | Routes to `cupcast-club-model` (default fallback) | MLflow `@prod` alias |

WC routing is special — historical training data only has CLUB matches, so the EPL specialist would silently produce zero-filled garbage on national-team fixtures. The Elo system replaces that path.

## World Cup specifics

### Elo predictor v1
- Walk-forward Elo computation from `intl_matches.parquet` (49,215 historical international matches)
- World Football Elo conventions: K = 60 (WC), 50 (continental), 40 (qualifier), 30 (friendly)
- Goal-difference modifier on K
- Home-field advantage = +100 elo (0 at neutral venue)
- **Draw probability** fitted from data via piecewise table (`draw_model_params.json`); peaks at ~28% when elo gap = 0, declines as |gap|/300

### Validated Elo metrics on holdout (WC22 + Euro24 + Copa24)
- Accuracy: 51.0%
- Brier score: 0.605
- Log-loss: 1.018
- Known limitation: never picks Draw as argmax (architectural cap of multiplicative split with feature-poor inputs — fix requires richer features in future model)

### Monte Carlo tournament simulator
- 10k simulations cached in `tournament_simulations` table
- Group sampling from per-match Elo probabilities
- Knockouts use Bradley-Terry win-expectancy on current Elo
- In-sim Elo updates after each round (so deeper-run teams compound their advantage)
- Reproducible via seed
- Runtime: ~3.4s on Cloud Run

### Title odds output (current)
| Team | Win % | Reach Final % |
|---|---|---|
| Spain | 22.4% | 34.3% |
| Argentina | 18.1% | 29.1% |
| France | 12.5% | 22.3% |
| Brazil | 5.7% | 11.8% |
| England | 5.4% | 11.1% |

## Score validation safety net

> [!success] Production-grade defense in depth
> The Apr 24 outage taught us not to trust a single data feed. Now: 3 layers of correction + persistent audit trail.

```
┌────────────────────────────────────────────────────┐
│  Match completes upstream                          │
└────────────────┬───────────────────────────────────┘
                 │
                 ▼
        ┌──────────────────┐
        │  Time guard      │  Won't mark complete
        │  kickoff+105min  │  before this elapses
        │  (cup: +130min)  │
        └────────┬─────────┘
                 │ ✓
                 ▼
        ┌──────────────────┐
        │  Mark complete   │
        └────────┬─────────┘
                 │
                 ▼
   ┌──────────────────────────┐
   │  6-hour re-check window  │  Score can still be
   │  (cross-source vs        │  revised within 6h
   │   API-Football)          │
   └────────────┬─────────────┘
                │ (after 6h)
                ▼
   ┌──────────────────────────┐
   │  Cron: revalidation /6h  │  Daily cross-source
   │  Audits past 2 days,     │  audit catches anything
   │  auto-fixes mismatches   │  the above missed
   └────────────┬─────────────┘
                │
                ▼
        ┌──────────────────┐
        │  score_corrections│  Persistent audit log
        │  table            │
        └──────────────────┘
```

## Frontend route map

| Route | What it shows |
|---|---|
| `/` | Dashboard hub — Featured Prediction + 3 KPIs + 6 country tiles |
| `/matches` | Today/Upcoming/Recent tabs, league filter pills, 2-up card grid |
| `/matches?country=england&tab=upcoming` | Pre-filtered |
| `/match/:id` | Full match detail — hero crests, prob bar, 3-col odds, H2H |
| `/world-cup` | Predictions tab (default) — Hero, Predicted Winner, Title Contenders |
| `/world-cup?tab=groups` | Groups & Stats tab — KPIs, GroupCard grid, Opening Match Prediction |
| `/about` | (unchanged from pre-session) |
| `/model-performance` | Lean metrics-only page |

## Key file map

```
backend/
├── api/
│   ├── matches.py        — /matches/*
│   ├── predictions.py    — /predictions/* (value picks)
│   ├── world_cup.py      — /world-cup/* (NEW)
│   ├── admin.py          — /admin/*
│   └── ...
├── services/
│   ├── national_elo.py           — Elo math (NEW)
│   ├── tournament_simulator.py   — Monte Carlo (NEW)
│   ├── group_standings.py        — pure standings + tiebreakers (NEW)
│   ├── wc_rationale.py           — templated winner rationale (NEW)
│   ├── prediction_service.py     — routing + WC fork
│   ├── score_updater.py          — 6h re-check + time guard
│   └── ...
├── scripts/
│   ├── revalidate_recent_scores.py  — safety net (NEW)
│   ├── compute_team_elo.py          — backfill (NEW)
│   ├── seed_missing_clubs.py        — auto-seed (NEW)
│   ├── seed_mls_fixtures.py         — MLS fixtures (NEW)
│   └── ... (3 more backfills)
├── migrations/versions/   — 7 new migrations
└── models/                — 3 new SQLAlchemy models

frontend/src/
├── pages/
│   ├── Dashboard.jsx         — rewrite
│   ├── Matches.jsx           — NEW
│   ├── MatchDetail.jsx       — refresh
│   └── WorldCup.jsx          — NEW (replaces WorldCupHub)
└── components/
    ├── match/
    │   ├── MatchRow.jsx           — NEW (v1 two-up cards)
    │   ├── FeaturedPrediction.jsx — NEW
    │   └── TeamCrest.jsx          — NEW (hashed-color initials fallback)
    ├── ui/
    │   ├── CountryFlag.jsx        — NEW (bundled flag-icons)
    │   ├── CountryFlagSvg.jsx     — inline SVGs (legacy, used by Dashboard tiles)
    │   ├── CountryCard.jsx        — NEW
    │   ├── LeagueFilterBar.jsx    — NEW
    │   ├── Pagination.jsx         — NEW
    │   └── Tabs.jsx               — NEW (ARIA + arrow-key)
    └── worldcup/                  — 8 components, all NEW

infra/
└── gcp/scheduler.sh        — 6 cron job definitions (NEW)

mlops/
├── reports/                — Elo validation reports + calibration plots
└── scripts/                — Fitting + validation harness
```
