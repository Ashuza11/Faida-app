# src/Dockerfile
FROM python:3.11-slim

# Keep Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set directory for the app (match the reference repo)
WORKDIR /code

# System deps for psycopg2 (Postgres driver)
RUN apt-get update \
    && apt-get -y install --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install to make use of Docker cache
COPY requirements.txt .
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt

# Copy application code
COPY . .

# Create a non-root user (same pattern as reference)
RUN adduser -u 5678 --disabled-password --gecos "" appuser \
    && chown -R appuser /code
USER appuser

# Expose the app port (matches gunicorn.conf.py below)
EXPOSE 50505

# Use the production entrypoint by default
ENTRYPOINT ["/code/entrypoint.sh"]
