from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.enums import UserRole
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.auth_disabled:
        user = db.scalar(select(User).where(User.username == "admin"))
        if user is None:
            raise AppError("DEMO_USER_MISSING", "Demo admin user is missing.", 500)
        return user

    if credentials is None:
        raise AppError("TOKEN_MISSING", "Bearer token is required.", 401)

    payload = decode_access_token(credentials.credentials, settings.jwt_secret)
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise AppError("TOKEN_INVALID", "Token is invalid.", 401)

    user = db.scalar(select(User).where(User.id == subject))
    if user is None:
        raise AppError("TOKEN_INVALID", "Token is invalid.", 401)

    if not user.is_active:
        raise AppError("USER_DISABLED", "User is disabled.", 403)

    return user


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    allowed_roles = set(roles)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise AppError("INSUFFICIENT_ROLE", "User does not have the required role.", 403)
        return user

    return dependency
