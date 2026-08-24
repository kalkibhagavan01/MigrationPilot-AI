from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MockTargetRecord(Base, TimestampMixin):
    __tablename__ = "mock_target_records"

    target_record_id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    employee_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class MockTargetFailure(Base):
    __tablename__ = "mock_target_failures"

    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
