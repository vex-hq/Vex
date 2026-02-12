FROM python:3.11-slim

WORKDIR /app

# Copy the shared models package into a location where
# `import shared.models` resolves correctly via PYTHONPATH.
COPY services/shared /app/lib/shared
ENV PYTHONPATH="/app/lib/shared"

# Install shared package dependencies (pydantic, sqlalchemy, psycopg2).
RUN pip install --no-cache-dir pydantic>=2.0.0 sqlalchemy>=2.0.0 psycopg2-binary>=2.9.0

# Install the ingestion API service.
COPY services/ingestion-api/pyproject.toml /app/
COPY services/ingestion-api/app /app/app
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
