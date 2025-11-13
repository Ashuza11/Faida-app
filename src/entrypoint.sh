#!/bin/sh

# This script waits for the database to be ready (which depends_on.condition already helps with)
# It then runs all setup commands from your 'airtfast_setup' service

echo "Running database migrations..."
flask db upgrade

echo "Running application setup..."
flask setup create-superadmin
flask setup init-stock

# Calculate yesterday's date (using sh-compatible syntax)
YESTERDAY=$(date -I -d 'yesterday')
echo "Seeding reports for $YESTERDAY..."
flask setup seed-reports --date "$YESTERDAY"

echo "Setup complete. Starting the Flask application..."

# Now, execute the main command to run the app
# This runs Flask on port 5000, accessible from all network interfaces
exec flask run --host=0.0.0.0 --port=5000