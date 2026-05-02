"""Auth: login, register, logout, /me, password change."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_unauthed_endpoints_return_401(client: TestClient) -> None:
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/metrics/summary").status_code == 401


def test_login_with_default_admin(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "admin"
    assert body["access_token"]


def test_login_with_wrong_password(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "wrong"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


def test_register_creates_user(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "alice123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "alice"
    assert body["user"]["role"] == "user"


def test_register_duplicate_username_409(client: TestClient) -> None:
    client.post("/api/auth/register", json={"username": "bob", "password": "bob1234"})
    second = client.post("/api/auth/register", json={"username": "bob", "password": "bob1234"})
    assert second.status_code == 409


def test_me_returns_current_user(client: TestClient, admin_headers: dict) -> None:
    resp = client.get("/api/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"


def test_logout_revokes_token(client: TestClient, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Token works before logout
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    # Revoke
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    # Same token now rejected
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_change_password_requires_current(client: TestClient, admin_headers: dict) -> None:
    bad = client.post(
        "/api/auth/change-password",
        json={"current_password": "wrong", "new_password": "newpass"},
        headers=admin_headers,
    )
    assert bad.status_code == 403

    good = client.post(
        "/api/auth/change-password",
        json={"current_password": "admin", "new_password": "newpass"},
        headers=admin_headers,
    )
    assert good.status_code == 200

    # The old password no longer works
    relogin = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert relogin.status_code == 401
