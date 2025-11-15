#!/bin/sh
set -e

echo "Running database migrations..."
flask db upgrade

echo "Starting gunicorn in development mode (reload enabled)..."
exec gunicorn -c gunicorn-cfg.py --reload run:app
