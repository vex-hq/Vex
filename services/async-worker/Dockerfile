FROM python:3.11-slim

WORKDIR /app

# Copy the shared models package and verification engine.
COPY services/shared /app/lib/shared
COPY services/verification-engine /app/lib/verification-engine
ENV PYTHONPATH="/app/lib:/app/lib/verification-engine"

# Install shared + verification-engine dependencies.
RUN pip install --no-cache-dir pydantic>=2.0.0 litellm>=1.0.0 jsonschema>=4.0.0

# Install the async worker service.
COPY services/async-worker/pyproject.toml /app/
COPY services/async-worker/app /app/app
RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.main"]
