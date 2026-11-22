FROM python:3.13-slim

WORKDIR /app

# dependencies first, so rebuilds are fast when only code changes
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# only what the API needs at runtime
COPY src/api.py src/model.py ./src/
COPY src/static ./src/static
COPY models ./models
COPY data/processed/database.db data/processed/corrections.csv data/processed/districts.geojson ./data/processed/

# run from src/ so the pickled model can find its "model" module
WORKDIR /app/src
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
