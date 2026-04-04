FROM python:3.11-slim

WORKDIR /app

# Install uv and dependencies
COPY requirements.txt .
RUN pip install uv && uv pip install --system --no-cache -r requirements.txt

# Copy API code and model
COPY api/ api/
COPY ml/models/cupcast-club_best.joblib ml/models/cupcast-club_best.joblib

# Expose port
EXPOSE 8000

# MLflow tracking URI must be passed at runtime:
#   docker run -e MLFLOW_TRACKING_URI=http://<IP>:5000 -p 8000:8000 cupcast-api

# Start the API server
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
