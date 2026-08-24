from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.seed import seed_demo_users
from app.models.base import Base


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        seed_demo_users(db)
