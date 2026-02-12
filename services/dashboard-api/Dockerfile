FROM python:3.11-slim

WORKDIR /app

# Install the dashboard API service.
COPY services/dashboard-api/pyproject.toml /app/
COPY services/dashboard-api/app /app/app
RUN pip install --no-cache-dir .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
