#!/bin/sh
# Faida App — Docker entrypoint
# Handles three database states on startup:
#   1. Fresh DB (no tables, no alembic_version)  → full upgrade from scratch
#   2. Tables exist, alembic_version missing/stale → stamp head, then upgrade (no-op)
#   3. Tables exist, alembic_version correct       → upgrade is already a no-op

set -e

echo "==> Inspecting database state..."

python - <<'PYEOF'
import sqlalchemy as sa
import os, sys

url = os.environ.get('DATABASE_URL', '')
if not url:
    print("No DATABASE_URL — skipping inspection")
    sys.exit(0)

if url.startswith('postgres://'):
    url = url.replace('postgres://', 'postgresql://', 1)

engine = sa.create_engine(url)

# Check whether core tables already exist
try:
    inspector = sa.inspect(engine)
    tables_exist = 'users' in inspector.get_table_names()
except Exception as e:
    print(f"Could not inspect DB: {e}")
    tables_exist = False

# Always clear alembic_version so we control what Alembic sees
with engine.begin() as conn:
    try:
        conn.execute(sa.text('DELETE FROM alembic_version'))
        print("Cleared alembic_version")
    except Exception:
        pass  # table may not exist yet — that is fine

if tables_exist:
    print("Tables already exist — will stamp to head (skip recreation)")
    # Signal to the shell: stamp before upgrade
    open('/tmp/db_needs_stamp', 'w').close()
else:
    print("Fresh database — full upgrade will run")
PYEOF

if [ -f /tmp/db_needs_stamp ]; then
    echo "==> Stamping alembic_version to head..."
    flask db stamp head
    rm -f /tmp/db_needs_stamp
fi

echo "==> Running flask db upgrade..."
flask db upgrade

echo "==> Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 --reload --workers 1 --timeout 120 run:app
