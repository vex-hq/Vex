FROM python:3.11-slim

WORKDIR /app

# Copy the shared models package.
COPY services/shared /app/lib/shared
ENV PYTHONPATH="/app/lib"

# Install shared package dependencies (pydantic).
RUN pip install --no-cache-dir pydantic>=2.0.0

# Install the alert service.
COPY services/alert-service/pyproject.toml /app/
COPY services/alert-service/app /app/app
RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.main"]
