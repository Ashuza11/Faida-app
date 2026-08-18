from pathlib import Path
import re


MIGRATIONS = Path(__file__).parents[2] / "migrations" / "versions"


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
