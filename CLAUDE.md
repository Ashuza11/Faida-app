# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run from `src/`:

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server (uses SQLite by default when FLASK_ENV unset)
flask run

# Run with Docker
docker-compose up --build

# Run tests
pytest

# Run a single test file
pytest tests/test_routes.py -v

# With coverage
pytest --cov=apps --cov-report=html

# Lint (critical errors only)
flake8 src/apps --count --select=E9,F63,F7,F82 --show-source

# Database migrations
flask db migrate -m "description"
flask db upgrade
flask db downgrade

# Setup CLI (platform admin / vendeur / invite codes)
flask setup create-platform-admin
flask setup create-vendeur
flask setup create-invite-code --expires-days 7
flask setup list-vendeurs
```

## Environment

Copy `.env.development` to `.env` or create one:

```bash
FLASK_APP=run.py
FLASK_ENV=development   # production | development | debug (SQLite) | testing (in-memory SQLite)
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///db.sqlite3  # or Neon PostgreSQL URL
```

`FLASK_ENV=debug` or unset → SQLite (no DB setup needed for quick iteration).

## Architecture

**Entry point:** `src/run.py` → calls `create_app()` from `src/apps/__init__.py`  
**Config:** `src/apps/config.py` — four config classes selected by `FLASK_ENV`  
**Models:** `src/apps/models.py` — single file for all ORM models  
**Migrations:** `src/migrations/` (Flask-Migrate / Alembic)

### Blueprints

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `main_bp` | `/` | Dashboard, sales, stock, clients, reports, PDF export |
| `auth_bp` | `/auth` | Login, register, logout (phone-based auth) |
| `admin_bp` | `/` | Platform admin — sees all businesses |
| `api_bp` | `/api/v1` | REST API (flask-restx) |
| `pdf_bp` | `/pdf` | PDF report generation (reportlab) |
| `errors_bp` | — | 404/500 error handlers |
| `health_bp` | `/health` | Health check |

### Multi-tenancy

Three roles: **PLATFORM_ADMIN**, **VENDEUR**, **STOCKEUR**.

- `get_current_vendeur_id()` in `decorators.py`: returns `None` for admin (no filter), `user.id` for vendeur, `user.vendeur_id` for stockeur.
- `filter_by_vendeur(query, Model)`: appends `.filter(Model.vendeur_id == vendeur_id)` — every query touching tenant data must go through this.
- Platform admin bypasses all filters and sees aggregate data across all businesses.

### Key files for business logic

- `src/apps/main/routes.py` (~83 KB) — sales, stock purchases, clients, cash flows, reports
- `src/apps/main/utils.py` — `get_daily_report_data()`, `update_daily_reports()`, `custom_round_up()`
- `src/apps/main/pdf_utils.py` — reportlab PDF generation helpers
- `src/apps/decorators.py` — `get_current_vendeur_id()`, `filter_by_vendeur()`, role-check decorators
- `src/apps/cli.py` — all `flask setup` commands

### Domain model summary

- **User** — phone-based login; role determines scope
- **InviteCode** — controls vendeur registration
- **Stock** — per network operator (airtel, vodacom, orange, africel) per vendeur
- **StockPurchase** — incoming inventory transactions
- **Sale / SaleItem** — sales with line items; debt tracking
- **CashInflow / CashOutflow** — manual accounting entries
- **DailyStockReport / DailyOverallReport** — pre-aggregated daily metrics

### Phone numbers

- DRC format only: normalized to `+243XXXXXXXXX`
- Valid prefixes enforced: Vodacom, Airtel, Orange, Africell
- Phone is the primary login identifier (no email login)

### PWA / Service Worker

Static assets include a Service Worker (`/sw.js`), `offline.html`, and `manifest.json`. The SW route is registered directly in `run.py`.
