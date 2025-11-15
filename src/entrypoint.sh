#!/bin/sh
set -e

echo "Running database migrations..."
flask db upgrade


echo "Starting gunicorn (production)..."
exec gunicorn -c gunicorn-cfg.py run:app
