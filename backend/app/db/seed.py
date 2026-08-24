from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.security import hash_password
from app.models.user import User

DEMO_PASSWORD = "demo-password"

DEMO_USERS: tuple[tuple[str, UserRole], ...] = (
    ("consultant", UserRole.IMPLEMENTATION_CONSULTANT),
    ("senior_consultant", UserRole.SENIOR_IMPLEMENTATION_CONSULTANT),
    ("hr_steward", UserRole.HR_DATA_STEWARD),
    ("compensation_manager", UserRole.COMPENSATION_MANAGER),
    ("payroll_manager", UserRole.PAYROLL_MANAGER),
    ("admin", UserRole.SYSTEM_ADMIN),
)


def seed_demo_users(db: Session) -> None:
    existing_usernames = set(db.scalars(select(User.username)).all())
    for username, role in DEMO_USERS:
        if username in existing_usernames:
            continue

        db.add(
            User(
                username=username,
                password_hash=hash_password(DEMO_PASSWORD),
                role=role,
            )
        )

    db.commit()
