import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.schemas.audit import AuditEventCreate, AuditEventResponse


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def append(self, event: AuditEventCreate) -> AuditEvent:
        audit_event = AuditEvent(
            migration_id=event.migration_id,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            event_type=event.event_type,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            before_json=_dump_json(event.before),
            after_json=_dump_json(event.after),
            reason=event.reason,
            metadata_json=_dump_json(event.metadata),
        )
        self.db.add(audit_event)
        self.db.commit()
        self.db.refresh(audit_event)
        return audit_event

    def list_for_migration(self, migration_id: str) -> list[AuditEvent]:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.migration_id == migration_id)
            .order_by(AuditEvent.created_at)
        )
        return list(self.db.scalars(statement).all())


def audit_event_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        migration_id=event.migration_id,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        event_type=event.event_type,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        before=_load_json(event.before_json),
        after=_load_json(event.after_json),
        reason=event.reason,
        metadata=_load_json(event.metadata_json),
        created_at=event.created_at,
    )


def _dump_json(value: dict[str, object] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


def _load_json(value: str | None) -> dict[str, object] | None:
    if value is None:
        return None
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else None
