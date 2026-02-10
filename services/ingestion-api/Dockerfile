FROM python:3.11-slim

WORKDIR /app

# Copy the shared models package into a location where
# `import shared.models` resolves correctly via PYTHONPATH.
COPY services/shared /app/lib/shared
ENV PYTHONPATH="/app/lib"

# Install shared package dependencies (pydantic).
RUN pip install --no-cache-dir pydantic>=2.0.0

# Install the ingestion API service.
COPY services/ingestion-api/pyproject.toml /app/
COPY services/ingestion-api/app /app/app
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
