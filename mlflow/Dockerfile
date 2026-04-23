# CupCast MLFlow Tracking Server
# Runs the MLFlow server backed by PostgreSQL.
# Used in local development (docker-compose) only.
# In GCP production, the MLFlow server is not deployed —
# model artifacts are stored in GCS and loaded directly.

FROM python:3.11-slim

# curl is required for the Docker Compose healthcheck on this container
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir mlflow[extras]>=2.10.0 psycopg2-binary>=2.9.9

EXPOSE 5000

COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
