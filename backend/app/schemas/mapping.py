from pydantic import BaseModel, Field, field_validator

from app.core.constants import TARGET_FIELD_TYPES
from app.core.enums import MappingDecision


class AlternativeMapping(BaseModel):
    target_field: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    @field_validator("target_field")
    @classmethod
    def target_field_must_exist(cls, value: str) -> str:
        if value not in TARGET_FIELD_TYPES:
            raise ValueError("target_field is not in target schema")
        return value


class MappingCandidate(BaseModel):
    source_field: str
    target_field: str | None
    semantic_confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str
    alternatives: list[AlternativeMapping] = Field(default_factory=list)

    @field_validator("target_field")
    @classmethod
    def target_field_must_exist(cls, value: str | None) -> str | None:
        if value is not None and value not in TARGET_FIELD_TYPES:
            raise ValueError("target_field is not in target schema")
        return value


class MappingResponseItem(BaseModel):
    id: str
    source_column: str
    target_field: str | None
    semantic_score: float
    name_score: float
    type_score: float
    value_score: float
    final_score: float
    decision: MappingDecision
    reasoning: str | None


class GenerateMappingsResponse(BaseModel):
    migration_id: str
    mappings: list[MappingResponseItem]
