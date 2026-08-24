from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == request.username))
    if user is None or not verify_password(request.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Invalid username or password.", 401)

    if not user.is_active:
        raise AppError("USER_DISABLED", "User is disabled.", 403)

    expires_delta = timedelta(minutes=settings.jwt_expires_minutes)
    token = create_access_token(user.id, settings.jwt_secret, expires_delta)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expires_minutes * 60,
        user=UserResponse(id=user.id, username=user.username, role=user.role),
    )


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, username=user.username, role=user.role)
