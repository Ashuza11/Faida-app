"""
Flask CLI Commands for Faida - Multi-Tenant

Commands:
- setup init: Full initialization
- setup create-platform-admin: Create platform admin
- setup create-invite-code: Generate invite code for new vendeur
- setup create-vendeur: Directly create vendeur (bypasses invite code)
- setup list-vendeurs: List all vendeurs
- setup check: System status check
"""

import click
import secrets
from flask import current_app
from flask.cli import with_appcontext
from datetime import datetime, timezone, timedelta


def register_cli_commands(app):
    """Register custom CLI commands with the Flask app."""

    @app.cli.group()
    def setup():
        """Application setup and management commands."""
        pass

    # ===========================================
    # Platform Admin Commands
    # ===========================================

    @setup.command("create-platform-admin")
    @click.option('--username', default='admin', help='Admin username')
    @click.option('--phone', prompt='Phone number (e.g., +243812345678)', help='Phone number')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option('--email', default=None, help='Email (optional)')
    @with_appcontext
    def create_platform_admin(username, phone, password, email):
        """Create the platform administrator account."""
        from apps import db
        from apps.models import User, RoleType, normalize_phone, validate_drc_phone

        # Check if platform admin already exists
        existing = User.query.filter_by(role=RoleType.PLATFORM_ADMIN).first()
        if existing:
            click.echo(
                f"⚠️  Platform admin already exists: {existing.username}")
            click.echo("   Only one platform admin is allowed.")
            return

        # Validate phone
        if not validate_drc_phone(phone):
            click.echo(
                "❌ Invalid phone number format. Use format: +243812345678 or 0812345678")
            raise click.Abort()

        # Check if phone already used
        normalized_phone = normalize_phone(phone)
        if User.query.filter_by(phone=normalized_phone).first():
            click.echo("❌ Phone number already in use")
            raise click.Abort()

        try:
            admin = User(
                username=username,
                phone=normalized_phone,
                email=email,
                role=RoleType.PLATFORM_ADMIN,
                is_active=True,
            )
            admin.set_password(password)

            db.session.add(admin)
            db.session.commit()

            click.echo("✅ Platform admin created successfully!")
            click.echo(f"   Username: {username}")
            click.echo(f"   Phone: {normalized_phone}")
            click.echo(f"   Role: PLATFORM_ADMIN")

        except Exception as e:
            db.session.rollback()
            click.echo(f"❌ Failed to create admin: {e}")
            raise click.Abort()

    # ===========================================
    # Invite Code Commands
    # ===========================================

    @setup.command("create-invite-code")
    @click.option('--expires-days', default=7, type=int, help='Days until expiration (default: 7)')
    @with_appcontext
    def create_invite_code(expires_days):
        """Generate an invite code for a new vendeur."""
        from apps import db
        from apps.models import User, RoleType, InviteCode

        # Get platform admin (for created_by)
        admin = User.query.filter_by(role=RoleType.PLATFORM_ADMIN).first()

        # Generate unique code
        code = f"AIRT-{secrets.token_hex(4).upper()}"

        # Ensure uniqueness
        while InviteCode.query.filter_by(code=code).first():
            code = f"AIRT-{secrets.token_hex(4).upper()}"

        try:
            invite = InviteCode(
                code=code,
                created_by_id=admin.id if admin else None,
                expires_at=datetime.now(timezone.utc) +
                timedelta(days=expires_days),
            )

            db.session.add(invite)
            db.session.commit()

            click.echo("✅ Invite code created!")
            click.echo(f"\n   Code: {code}")
            click.echo(f"   Expires in: {expires_days} days")
            click.echo(f"\n📱 Registration link:")
            click.echo(f"   /auth/register?code={code}")

        except Exception as e:
            db.session.rollback()
            click.echo(f"❌ Failed to create invite code: {e}")
            raise click.Abort()

    @setup.command("list-invite-codes")
    @with_appcontext
    def list_invite_codes():
        """List all invite codes."""
        from apps.models import InviteCode

        codes = InviteCode.query.order_by(InviteCode.created_at.desc()).all()

        if not codes:
            click.echo("No invite codes found.")
            return

        click.echo("\n📋 Invite Codes:")
        click.echo("-" * 50)

        for code in codes:
            status = "✅ Valid" if code.is_valid else "🔴 Used/Expired"
            click.echo(f"   {code.code} - {status}")

    # ===========================================
    # Vendeur Management Commands
    # ===========================================

    @setup.command("create-vendeur")
    @click.option('--username', prompt='Business name', help='Business name')
    @click.option('--phone', prompt='Phone number', help='Phone')
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option('--email', default=None, help='Email (optional)')
    @with_appcontext
    def create_vendeur_directly(username, phone, password, email):
        """Create a vendeur account directly (bypasses invite code)."""
        from apps import db
        from apps.models import (
            User, RoleType,
            normalize_phone, validate_drc_phone,
            create_stock_for_vendeur
        )

        # Validate phone
        if not validate_drc_phone(phone):
            click.echo("❌ Invalid phone number format")
            raise click.Abort()

        normalized_phone = normalize_phone(phone)

        # Check uniqueness
        if User.query.filter_by(phone=normalized_phone).first():
            click.echo("❌ Phone number already in use")
            raise click.Abort()

        if User.query.filter_by(username=username).first():
            click.echo("❌ Username already in use")
            raise click.Abort()

        try:
            # Create vendeur
            vendeur = User(
                username=username,
                phone=normalized_phone,
                email=email,
                role=RoleType.VENDEUR,
                is_active=True,
            )
            vendeur.set_password(password)

            db.session.add(vendeur)
            db.session.flush()  # Get ID

            # Create stock items (one per network, balance 0)
            stocks = create_stock_for_vendeur(vendeur.id)

            db.session.commit()

            click.echo("✅ Vendeur created successfully!")
            click.echo(f"   Business: {username}")
            click.echo(f"   Phone: {normalized_phone}")
            click.echo(
                f"   Stock items: {len(stocks)} networks initialized with balance 0")

        except Exception as e:
            db.session.rollback()
            click.echo(f"❌ Failed to create vendeur: {e}")
            raise click.Abort()

    @setup.command("list-vendeurs")
    @with_appcontext
    def list_vendeurs():
        """List all vendeurs."""
        from apps.models import User, RoleType, Stock

        vendeurs = User.query.filter_by(role=RoleType.VENDEUR).all()

        if not vendeurs:
            click.echo("No vendeurs found.")
            return

        click.echo("\n📊 Vendeurs:")
        click.echo("-" * 60)

        for v in vendeurs:
            status = "✅ Active" if v.is_active else "❌ Inactive"
            stockeur_count = v.stockeurs.count()
            client_count = len(v.clients)
            click.echo(f"\n   {v.username} ({v.display_phone})")
            click.echo(f"      Status: {status}")
            click.echo(f"      Stockeurs: {stockeur_count}")
            click.echo(f"      Clients: {client_count}")
            click.echo(f"      Created: {v.created_at.strftime('%Y-%m-%d')}")

    # ===========================================
    # System Check Commands
    # ===========================================

    @setup.command("check")
    @with_appcontext
    def check_system():
        """Check system status and configuration."""
        from apps import db
        from apps.models import User, RoleType, Stock, Sale, Client
        from sqlalchemy import text
        import os

        click.echo("\n🔍 Faida App Multi-Tenant System Check")
        click.echo("=" * 50)

        # Environment
        click.echo(f"\n📋 Environment:")
        click.echo(f"   FLASK_ENV: {os.environ.get('FLASK_ENV', 'not set')}")
        click.echo(f"   Debug: {current_app.debug}")

        # Database
        click.echo(f"\n💾 Database:")
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if 'sqlite' in db_uri:
            click.echo("   Type: SQLite (local)")
        elif 'neon.tech' in db_uri:
            click.echo("   Type: Neon PostgreSQL")
        elif 'postgresql' in db_uri:
            click.echo("   Type: PostgreSQL")

        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            click.echo("   Connection: ✅ OK")
        except Exception as e:
            click.echo(f"   Connection: ❌ Failed - {e}")

        # Users
        click.echo(f"\n👥 Users:")
        admin_count = User.query.filter_by(
            role=RoleType.PLATFORM_ADMIN).count()
        vendeur_count = User.query.filter_by(role=RoleType.VENDEUR).count()
        stockeur_count = User.query.filter_by(role=RoleType.STOCKEUR).count()
        click.echo(f"   Platform Admins: {admin_count}")
        click.echo(f"   Vendeurs: {vendeur_count}")
        click.echo(f"   Stockeurs: {stockeur_count}")

        # Business Data
        click.echo(f"\n📊 Data:")
        click.echo(f"   Stock records: {Stock.query.count()}")
        click.echo(f"   Clients: {Client.query.count()}")
        click.echo(f"   Sales: {Sale.query.count()}")

        click.echo("\n✅ System check complete!")

    # ===========================================
    # Database Commands
    # ===========================================

    @app.cli.command("check-db")
    @with_appcontext
    def check_db():
        """Check database connection."""
        from apps import db
        from sqlalchemy import text

        try:
            with db.engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                click.echo("✅ Database connection successful!")

                if 'postgresql' in str(db.engine.url):
                    version = conn.execute(text("SELECT version()")).scalar()
                    click.echo(f"   PostgreSQL: {version[:60]}...")
        except Exception as e:
            click.echo(f"❌ Database connection failed: {e}")
            return 1

    # ===========================================
    # Initialization Command
    # ===========================================

    @setup.command("init")
    @with_appcontext
    def init_all():
        """Full system initialization (check connection + status)."""
        from apps import db
        from sqlalchemy import text

        click.echo("🚀 Faida Multi-Tenant Initialization")
        click.echo("=" * 50)

        # Check database connection
        click.echo("\n📡 Checking database connection...")
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            click.echo("   ✅ Database connected")
        except Exception as e:
            click.echo(f"   ❌ Database connection failed: {e}")
            click.echo("\n   Please check your DATABASE_URL configuration")
            raise click.Abort()

        # Check for platform admin
        click.echo("\n👤 Checking platform admin...")
        from apps.models import User, RoleType

        admin_exists = User.query.filter_by(
            role=RoleType.PLATFORM_ADMIN).first()
        if admin_exists:
            click.echo(f"   ✅ Platform admin exists: {admin_exists.username}")
        else:
            click.echo("   ⚠️  No platform admin found. Create one with:")
            click.echo("      flask setup create-platform-admin")

        # Count vendeurs
        vendeur_count = User.query.filter_by(role=RoleType.VENDEUR).count()
        click.echo(f"\n📊 Statistics:")
        click.echo(f"   Vendeurs: {vendeur_count}")

        click.echo("\n✨ Initialization complete!")
        click.echo("\nNext steps:")
        if not admin_exists:
            click.echo("   1. flask setup create-platform-admin")
        click.echo("   2. flask setup create-invite-code")
        click.echo("   3. Share invite code with new vendeur")
