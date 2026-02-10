# src/Dockerfile
# Faida App - Production Docker Image

FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /code

# Install system dependencies for psycopg2 (PostgreSQL driver)
RUN apt-get update \
    && apt-get -y install --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies (cached layer)
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN adduser -u 5678 --disabled-password --gecos "" appuser \
    && chown -R appuser /code
USER appuser

# Expose port
EXPOSE 5000

# Default command
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "run:app"]