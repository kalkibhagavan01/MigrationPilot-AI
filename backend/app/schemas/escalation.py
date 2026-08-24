from typing import Any, Literal

from app.core.enums import DataClassification, EscalationStatus, Severity, UserRole
from pydantic import BaseModel, Field


class EscalationResponse(BaseModel):
    id: str
    migration_id: str
    record_id: str | None
    issue_type: str
    severity: Severity
    classification: DataClassification
    required_role: UserRole
    status: EscalationStatus
    context: dict[str, Any]
    recommended_action: dict[str, Any] | None


class ResolveEscalationRequest(BaseModel):
    action: Literal["APPROVE", "CORRECT", "REJECT", "SEND_TO_HR"]
    resolution: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


class BuildEscalationsResponse(BaseModel):
    migration_id: str
    created: int
    open_blocking: int
