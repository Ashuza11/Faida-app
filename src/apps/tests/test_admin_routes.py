from apps.models import RoleType, User


def make_user(session, *, suffix, role, is_active=True):
    user = User(
        username=f"admin-route-{suffix}",
        phone=f"+243810009{suffix:03d}",
        role=role,
        is_active=is_active,
    )
    user.set_password("safe-password")
    session.add(user)
    session.flush()
    return user


def login(client, user):
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(user.id)
        browser_session["_fresh"] = True


def test_platform_admin_cannot_open_retail_dashboard(app, session):
    admin = make_user(
        session,
        suffix=1,
        role=RoleType.PLATFORM_ADMIN,
    )
    session.commit()
    client = app.test_client()
    login(client, admin)

    for path in ("/", "/index", "/auth/login"):
        response = client.get(path)

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/admin/dashboard")


def test_android_tokens_uses_username_and_generates_active_vendor_token(app, session):
    admin = make_user(
        session,
        suffix=2,
        role=RoleType.PLATFORM_ADMIN,
    )
    active_vendor = make_user(
        session,
        suffix=3,
        role=RoleType.VENDEUR,
    )
    inactive_vendor = make_user(
        session,
        suffix=4,
        role=RoleType.VENDEUR,
        is_active=False,
    )
    session.commit()
    client = app.test_client()
    login(client, admin)

    response = client.get("/admin/android-tokens")

    assert response.status_code == 200
    assert active_vendor.username.encode() in response.data
    assert inactive_vendor.username.encode() not in response.data
    session.refresh(active_vendor)
    assert active_vendor.api_token


def test_admin_can_regenerate_vendor_android_token(app, session):
    admin = make_user(
        session,
        suffix=5,
        role=RoleType.PLATFORM_ADMIN,
    )
    vendor = make_user(
        session,
        suffix=6,
        role=RoleType.VENDEUR,
    )
    vendor.api_token = "old-token"
    session.commit()
    client = app.test_client()
    login(client, admin)

    response = client.post(
        f"/admin/android-tokens/{vendor.id}/regenerate",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert vendor.username.encode() in response.data
    session.refresh(vendor)
    assert vendor.api_token != "old-token"

    invalid_target = client.post(
        f"/admin/android-tokens/{admin.id}/regenerate",
    )
    assert invalid_target.status_code == 404
