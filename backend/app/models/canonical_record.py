from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ValidationStatus
from app.models.base import Base, TimestampMixin, UpdatedAtMixin, new_uuid


class CanonicalRecord(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "canonical_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    migration_id: Mapped[str] = mapped_column(ForeignKey("migrations.id"), index=True, nullable=False)
    employee_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[ValidationStatus] = mapped_column(String, index=True, nullable=False)
    validation_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issues_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
