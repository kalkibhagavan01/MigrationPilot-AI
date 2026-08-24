from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, new_uuid


class SourceFile(TimestampMixin, Base):
    __tablename__ = "source_files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    migration_id: Mapped[str] = mapped_column(
        ForeignKey("migrations.id"),
        index=True,
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    stored_path: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String, nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    migration: Mapped["Migration"] = relationship(back_populates="source_files")
    column_profiles: Mapped[list["ColumnProfile"]] = relationship(
        back_populates="source_file",
        cascade="all, delete-orphan",
    )
