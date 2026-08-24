from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, new_uuid


class ColumnProfile(Base):
    __tablename__ = "column_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("source_files.id"),
        index=True,
        nullable=False,
    )
    sheet_name: Mapped[str | None] = mapped_column(String, nullable=True)
    column_name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    inferred_type: Mapped[str] = mapped_column(String, nullable=False)
    null_ratio: Mapped[float] = mapped_column(nullable=False)
    unique_ratio: Mapped[float] = mapped_column(nullable=False)
    sample_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    profile_json: Mapped[str] = mapped_column(Text, nullable=False)

    source_file: Mapped["SourceFile"] = relationship(back_populates="column_profiles")
