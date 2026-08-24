from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import MappingDecision
from app.models.base import Base, TimestampMixin, UpdatedAtMixin, new_uuid


class Mapping(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "mappings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    migration_id: Mapped[str] = mapped_column(ForeignKey("migrations.id"), index=True, nullable=False)
    source_file_id: Mapped[str] = mapped_column(ForeignKey("source_files.id"), nullable=False)
    source_column: Mapped[str] = mapped_column(String, nullable=False)
    target_field: Mapped[str | None] = mapped_column(String, nullable=True)
    semantic_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    name_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    type_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    value_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    final_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    decision: Mapped[MappingDecision] = mapped_column(String, index=True, nullable=False)
    decision_source: Mapped[str] = mapped_column(String, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternatives_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
