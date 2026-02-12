FROM python:3.11-slim

WORKDIR /app

# Copy the shared models package.
COPY services/shared /app/lib/shared
ENV PYTHONPATH="/app/lib/shared"

# Install shared package dependencies (pydantic, sqlalchemy, psycopg2).
RUN pip install --no-cache-dir pydantic>=2.0.0 sqlalchemy>=2.0.0 psycopg2-binary>=2.9.0

# Install the alert service.
COPY services/alert-service/pyproject.toml /app/
COPY services/alert-service/app /app/app
RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.main"]
