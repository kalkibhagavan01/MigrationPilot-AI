from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.migration import Migration
from app.models.user import User
from app.schemas.audit import AuditEventResponse
from app.services.audit import AuditService, audit_event_response
from app.services.masking import mask_sensitive_payload

router = APIRouter(prefix="/migrations/{migration_id}/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventResponse])
def list_audit_events(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AuditEventResponse]:
    if db.get(Migration, migration_id) is None:
        raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)
    responses = []
    for event in AuditService(db).list_for_migration(migration_id):
        response = audit_event_response(event)
        response.before = mask_sensitive_payload(response.before)
        response.after = mask_sensitive_payload(response.after)
        response.metadata = mask_sensitive_payload(response.metadata)
        responses.append(response)
    return responses
