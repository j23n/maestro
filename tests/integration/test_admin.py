def test_admin_dashboard_requires_login(auth_app):
    """Unauthenticated request to /admin/ redirects to login."""
    resp = auth_app.get("/admin/", follow_redirects=False)
    assert resp.status_code in (302, 303, 307)
    assert "/auth/login" in resp.headers["location"]


def test_admin_dashboard_non_admin_gets_403(test_app):
    """Authenticated non-admin user gets 403."""
    resp = test_app.get("/admin/")
    assert resp.status_code == 403


async def test_admin_dashboard_admin_gets_200(test_app, account):
    """Authenticated admin user sees the dashboard."""
    account.is_admin = True
    await account.save()
    resp = test_app.get("/admin/")
    assert resp.status_code == 200
    assert "Admin Dashboard" in resp.text


def test_admin_feedback_non_admin_gets_403(test_app):
    """Non-admin user gets 403 on feedback page."""
    resp = test_app.get("/admin/feedback")
    assert resp.status_code == 403


async def test_admin_feedback_admin_gets_200(test_app, account):
    """Authenticated admin user sees the feedback page."""
    account.is_admin = True
    await account.save()
    resp = test_app.get("/admin/feedback")
    assert resp.status_code == 200
    assert "LLM Critiques" in resp.text


def test_admin_feedback_requires_login(auth_app):
    """Unauthenticated request to /admin/feedback redirects to login."""
    resp = auth_app.get("/admin/feedback", follow_redirects=False)
    assert resp.status_code in (302, 303, 307)
    assert "/auth/login" in resp.headers["location"]
