from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DataClassification, EscalationStatus, Severity, UserRole
from app.models.base import Base, TimestampMixin, new_uuid


class Escalation(Base, TimestampMixin):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    migration_id: Mapped[str] = mapped_column(ForeignKey("migrations.id"), index=True, nullable=False)
    record_id: Mapped[str | None] = mapped_column(ForeignKey("canonical_records.id"), nullable=True)
    issue_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[Severity] = mapped_column(String, nullable=False)
    classification: Mapped[DataClassification] = mapped_column(String, nullable=False)
    required_role: Mapped[UserRole] = mapped_column(String, index=True, nullable=False)
    status: Mapped[EscalationStatus] = mapped_column(String, index=True, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution_json: Mapped[str | None] = mapped_column(Text, nullable=True)
