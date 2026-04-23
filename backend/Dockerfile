# CupCast Backend — FastAPI
# Multi-stage build to minimize production image size.
# Target: <800MB (xgboost + pandas + mlflow are large)
#
# Build context: cupcast/ (the repo root, NOT backend/)
# The compose file sets: build: { context: ., dockerfile: backend/Dockerfile }
# This is required so the ml/ directory is available during the build.

FROM python:3.11-slim AS builder

WORKDIR /build

# Install Python deps first (cached layer — only invalidated when requirements.txt changes)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.11-slim AS runtime

WORKDIR /app

# System deps:
#   curl  — used by the Docker Compose healthcheck (CMD curl -f http://localhost:8000/health)
#   libgomp1 — required by LightGBM (OpenMP runtime); absent on slim images
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl \
       libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application source
# backend/ → /app/  (FastAPI app, models, services, etc.)
# ml/      → /app/ml/ (feature engineering, config, trained model artifacts)
COPY backend/ .
COPY ml/ ./ml/

# PATH: include user-local pip binaries (uvicorn, alembic, etc.)
# PYTHONPATH: /app      → resolves bare imports like `from config import settings`
#             /app/ml   → allows `from ml.src.feature_engineering import ...`
#                         (ml/ is a package rooted at /app, so `import ml.src.*` works
#                          without any sys.path manipulation at runtime)
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app

# Cloud Run injects PORT=8080 at runtime. Default to 8000 for local/docker-compose.
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands at container start; exec replaces the shell with
# uvicorn as PID 1 so SIGTERM reaches it directly (clean shutdown on Cloud Run).
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
