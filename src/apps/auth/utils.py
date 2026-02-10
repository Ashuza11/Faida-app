from apps.main.utils import load_seed_data


def create_superadmin():
    from apps.models import User, RoleType
    from apps import db
    from flask import (
        current_app,
    )

    # Load data from JSON
    full_seed_data = load_seed_data()
    if not full_seed_data:
        return False

    admin_data = full_seed_data.get("superadmin_user")
    if not admin_data:
        current_app.logger.error(
            "Superadmin data not found in seed_data.json.")
        return False

    try:
        # Check if superadmin exists
        if not User.query.filter_by(role=RoleType.SUPERADMIN).first():
            superadmin = User(
                username=admin_data["username"],
                phone=admin_data["phone"],
                # email=admin_data["email"],
                email=admin_data.get("email"),
                role=RoleType.SUPERADMIN,
                is_active=True,
            )
            superadmin.set_password(admin_data["password"])
            db.session.add(superadmin)
            db.session.commit()

            current_app.logger.info(
                f"Superadmin user '{admin_data['username']}' created successfully from seed data."
            )
            return True

        current_app.logger.info("Superadmin user already exists.")
        return True

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"Error creating superadmin from seed data: {e}", exc_info=True
        )
        return False
