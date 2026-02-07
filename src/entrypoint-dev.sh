#!/bin/sh
# entrypoint-dev.sh - Development entrypoint with hot reload
# Used for local Docker development

set -e

echo "=========================================="
echo "🔧 Faida App Development Startup"
echo "=========================================="

# ===========================================
# Step 1: Wait for database
# ===========================================
echo ""
echo "📡 Checking database connection..."

MAX_RETRIES=30
RETRY_COUNT=0

# For development, we might be waiting for local PostgreSQL in Docker
until flask check-db 2>/dev/null; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "⚠️  Could not connect to database."
        echo "   Continuing anyway (might be using SQLite)..."
        break
    fi
    echo "   Attempt $RETRY_COUNT/$MAX_RETRIES - Waiting for database..."
    sleep 2
done

# ===========================================
# Step 2: Run migrations
# ===========================================
echo ""
echo "📦 Running database migrations..."
flask db upgrade || echo "⚠️  Migration warning (might be first run)"

# ===========================================
# Step 3: Initialize stock (idempotent)
# ===========================================
echo ""
echo "🔧 Initializing stock items..."
flask setup init-stock || echo "⚠️  Stock init warning"

# ===========================================
# Step 4: Start Gunicorn with reload
# ===========================================
echo ""
echo "=========================================="
echo "🔄 Starting Gunicorn (Development + Reload)..."
echo "=========================================="

exec gunicorn -c gunicorn-cfg.py --reload run:app