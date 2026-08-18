---
name: project-python-env
description: Use for Python commands, tests, package inspection, dependency installation, upgrades, or lockfile and requirements changes in the Faida project. Ensures all Python dependency operations run inside the repository's env virtual environment.
---

# Project Python Environment

Before running Python, pip, Flask, Alembic, or pytest commands, activate the project environment:

```shell
source env/bin/activate
```

When the working directory is `src`, use `source ../env/bin/activate`.

Install or update Python dependencies only through the activated environment. Prefer:

```shell
python -m pip install <package>
```

Never install Faida dependencies globally or with the system Python. After changing dependencies, update both `pyproject.toml` and `src/requirements.txt` when they are intended to remain parallel, then run the relevant tests inside the same environment.
