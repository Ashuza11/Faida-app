def create_superadmin():
    from apps.models import User, RoleType
    from apps import db

    try:
        # Check if superadmin exists
        if not User.query.filter_by(role=RoleType.SUPERADMIN).first():
            superadmin = User(
                username="superadmin",
                email="superadmin@example.com",
                role=RoleType.SUPERADMIN,
                is_active=True,
            )
            superadmin.set_password("Admin@123")
            db.session.add(superadmin)
            db.session.commit()
            return True
    except Exception as e:
        db.session.rollback()
        print(f"Error creating superadmin: {e}")
        return False
    return False
