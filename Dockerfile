FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API code and model
COPY api/ api/
COPY ml/models/cupcast-club_best.joblib ml/models/cupcast-club_best.joblib

# Expose port
EXPOSE 8000

# Set default MLflow tracking URI (can be overridden at runtime)
ENV MLFLOW_TRACKING_URI=http://34.58.128.38:5000

# Start the API server
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
