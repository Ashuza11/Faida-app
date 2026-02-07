#!/bin/sh
# entrypoint.sh - Production entrypoint for Render deployment
# This script runs before starting the application

set -e

echo "=========================================="
echo "🚀 Faida App Production Startup"
echo "=========================================="

# ===========================================
# Step 1: Wait for database (Neon might be cold)
# ===========================================
echo ""
echo "📡 Waiting for database connection..."

MAX_RETRIES=10
RETRY_COUNT=0

until flask check-db 2>/dev/null; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "❌ Could not connect to database after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "   Attempt $RETRY_COUNT/$MAX_RETRIES - Database not ready, waiting 3s..."
    sleep 3
done

echo "✅ Database connected!"

# ===========================================
# Step 2: Run migrations
# ===========================================
echo ""
echo "📦 Running database migrations..."
flask db upgrade

if [ $? -eq 0 ]; then
    echo "✅ Migrations complete!"
else
    echo "❌ Migration failed!"
    exit 1
fi

# ===========================================
# Step 3: Initialize required data (idempotent)
# ===========================================
echo ""
echo "🔧 Initializing stock items..."
flask setup init-stock

# ===========================================
# Step 4: Start Gunicorn
# ===========================================
echo ""
echo "=========================================="
echo "🌐 Starting Gunicorn (Production)..."
echo "=========================================="

exec gunicorn -c gunicorn-cfg.py run:app