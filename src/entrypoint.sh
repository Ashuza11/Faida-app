#!/bin/sh
# Production startup: migrate the configured database before serving requests.

set -eu

echo "==> Applying database migrations..."
flask db upgrade

echo "==> Database migrations complete."
echo "==> Starting Gunicorn..."
exec gunicorn \
    --bind "0.0.0.0:${PORT:-5000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout 120 \
    run:app
