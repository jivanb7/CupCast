# CupCast ML Service Dockerfile
# Used for running the training pipeline and batch prediction generation.
# NOT used at API request time — predictions are pre-computed and stored in Postgres.
#
# Build context: repo root (saas/), NOT ml/ — so the Dockerfile can COPY ml/
# into /app/ml/ and preserve the package layout that the code assumes.
# Example: docker build -f ml/Dockerfile -t cupcast-ml:latest .
#
# Target image size: <1.2GB (xgboost + pandas + shap are large)

FROM python:3.11-slim AS builder

WORKDIR /build

COPY ml/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy the whole ml/ package so `from ml.src.xxx import ...` resolves.
COPY ml/ ./ml/

# PATH: user-local pip binaries (e.g. mlflow CLI)
# PYTHONPATH: /app so `ml.run_pipeline` and `ml.src.*` are importable
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app

# Data directories (mounted as volumes or populated at runtime)
RUN mkdir -p /app/ml/data/raw /app/ml/data/processed /app/ml/data/features /app/ml/models

CMD ["python", "-m", "ml.run_pipeline", "--mode", "predict-only"]
