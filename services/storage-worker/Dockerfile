FROM python:3.11-slim

WORKDIR /app

# Copy the shared models package into a location where
# `import shared.models` resolves correctly via PYTHONPATH.
COPY services/shared /app/lib/shared
ENV PYTHONPATH="/app/lib"

# Install shared package dependencies (pydantic).
RUN pip install --no-cache-dir pydantic>=2.0.0

# Install the storage worker service.
COPY services/storage-worker/pyproject.toml /app/
COPY services/storage-worker/app /app/app
RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.main"]
