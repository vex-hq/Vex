FROM python:3.11-slim

WORKDIR /app

# Copy the shared models package into a location where
# `import shared.models` resolves correctly via PYTHONPATH.
COPY services/shared /app/lib/shared
COPY services/verification-engine /app/lib/verification-engine
ENV PYTHONPATH="/app/lib:/app/lib/verification-engine"

# Install shared + verification-engine dependencies.
RUN pip install --no-cache-dir pydantic>=2.0.0 litellm>=1.0.0 jsonschema>=4.0.0

# Install the sync gateway service.
COPY services/sync-gateway/pyproject.toml /app/
COPY services/sync-gateway/app /app/app
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
