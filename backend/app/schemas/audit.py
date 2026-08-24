from typing import Any

from app.core.enums import AuditActorType
from pydantic import BaseModel
from datetime import datetime


class AuditEventCreate(BaseModel):
    migration_id: str
    actor_type: AuditActorType
    actor_id: str | None = None
    event_type: str
    entity_type: str
    entity_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None


class AuditEventResponse(BaseModel):
    id: str
    migration_id: str
    actor_type: AuditActorType
    actor_id: str | None
    event_type: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
