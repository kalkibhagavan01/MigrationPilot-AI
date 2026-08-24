from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import MigrationStatus
from app.models.base import Base, TimestampMixin, UpdatedAtMixin, new_uuid


class Migration(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "migrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    status: Mapped[MigrationStatus] = mapped_column(String, index=True, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    target_schema_version: Mapped[str] = mapped_column(String, nullable=False)
    current_node: Mapped[str | None] = mapped_column(String, nullable=True)
    total_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source_files: Mapped[list["SourceFile"]] = relationship(
        back_populates="migration",
        cascade="all, delete-orphan",
    )
