from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.enums import UserRole
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.dependencies import require_roles
from app.main import create_app
from app.models.user import User
from app.schemas.auth import UserResponse


def make_client(database_url: str) -> TestClient:
    return TestClient(create_app(database_url=database_url))


def make_client_with_admin_route(database_url: str) -> TestClient:
    app = create_app(database_url=database_url)

    @app.get("/test/admin", response_model=UserResponse)
    def admin_only(user: User = Depends(require_roles(UserRole.SYSTEM_ADMIN))) -> UserResponse:
        return UserResponse(id=user.id, username=user.username, role=user.role)

    return TestClient(app)


def test_login_returns_jwt_and_user(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'auth.db'}") as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "consultant", "password": "demo-password"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 315_360_000
    assert body["access_token"]
    assert body["user"]["role"] == UserRole.IMPLEMENTATION_CONSULTANT


def test_password_hash_is_not_plaintext(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'hash.db'}"):
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == "consultant"))

    assert user is not None
    assert user.password_hash != "demo-password"
    assert user.password_hash.startswith("pbkdf2_sha256$")


def test_me_uses_demo_admin_without_token(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'me.db'}") as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_missing_token_is_allowed_in_demo_mode(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'missing.db'}") as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["role"] == UserRole.SYSTEM_ADMIN


def test_invalid_login_returns_401(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'invalid.db'}") as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "consultant", "password": "wrong"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_disabled_user_returns_403(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'disabled.db'}") as client:
        with SessionLocal() as db:
            db.add(
                User(
                    username="disabled",
                    password_hash=hash_password("demo-password"),
                    role=UserRole.IMPLEMENTATION_CONSULTANT,
                    is_active=False,
                )
            )
            db.commit()

        response = client.post(
            "/api/v1/auth/login",
            json={"username": "disabled", "password": "demo-password"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_DISABLED"


def test_expired_jwt_is_ignored_in_demo_mode(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'expired.db'}") as client:
        response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer expired"})

    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_role_guard_allows_demo_admin_without_token(tmp_path) -> None:
    with make_client_with_admin_route(f"sqlite:///{tmp_path / 'role.db'}") as client:
        response = client.get("/test/admin")

    assert response.status_code == 200
    assert response.json()["role"] == UserRole.SYSTEM_ADMIN


def test_role_guard_allows_admin(tmp_path) -> None:
    with make_client_with_admin_route(f"sqlite:///{tmp_path / 'admin.db'}") as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "demo-password"},
        )
        token = login.json()["access_token"]
        response = client.get(
            "/test/admin",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["role"] == UserRole.SYSTEM_ADMIN
