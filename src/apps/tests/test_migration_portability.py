import os
from pathlib import Path
import re
import subprocess
import sys


MIGRATIONS = Path(__file__).parents[2] / "migrations" / "versions"
SRC_ROOT = MIGRATIONS.parents[1]


def test_migration_sql_does_not_assign_integer_literals_to_booleans():
    integer_boolean = re.compile(
        r"(?:\b(?:is_active|is_cost_estimated)\s*=\s*[01]\b|"
        r"'(?:OWNER|STOCKEUR)'\s*,\s*[01]\s*,)"
    )

    violations = []
    for migration in MIGRATIONS.glob("*.py"):
        source = migration.read_text()
        if integer_boolean.search(source):
            violations.append(migration.name)

    assert violations == []


def test_postgresql_enum_case_backfill_has_an_explicit_cast():
    migration = MIGRATIONS / "b3a8cf947120_add_report_transaction_facts.py"
    source = migration.read_text()

    assert "::paymentallocationkind" in source


def test_legacy_to_head_postgresql_sql_reuses_base_enum_types():
    environment = {
        **os.environ,
        "FLASK_ENV": "production",
        "SECRET_KEY": "migration-test",
        "DATABASE_URL": "postgresql://test:test@localhost/test",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flask",
            "db",
            "upgrade",
            "d4b0b8e1bb3a:head",
            "--sql",
        ],
        cwd=SRC_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE TYPE networktype" not in result.stdout
    assert ")::paymentallocationkind" in result.stdout
