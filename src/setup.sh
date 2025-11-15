#!/bin/sh
set -e

echo "Running database migrations..."
flask db upgrade

echo "Creating super admin..."
flask setup create-superadmin

echo "Initializing stock..."
flask setup init-stock

YESTERDAY=$(date -I -d 'yesterday')
echo "Seeding reports for $YESTERDAY..."
flask setup seed-reports --date "$YESTERDAY"

echo "✨ Initial setup completed successfully!"
