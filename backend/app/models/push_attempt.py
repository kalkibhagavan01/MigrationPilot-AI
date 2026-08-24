from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PushStatus
from app.models.base import Base, TimestampMixin, new_uuid


class PushAttempt(Base, TimestampMixin):
    __tablename__ = "push_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    migration_id: Mapped[str] = mapped_column(ForeignKey("migrations.id"), index=True, nullable=False)
    record_id: Mapped[str] = mapped_column(ForeignKey("canonical_records.id"), index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    target_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PushStatus] = mapped_column(String, index=True, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
