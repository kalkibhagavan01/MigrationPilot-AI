from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import EscalationStatus
from app.core.errors import AppError
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.escalation import Escalation
from app.models.migration import Migration
from app.models.user import User
from app.schemas.escalation import (
    BuildEscalationsResponse,
    EscalationResponse,
    ResolveEscalationRequest,
)
from app.services.escalation import EscalationService

router = APIRouter(tags=["escalations"])


@router.post("/migrations/{migration_id}/escalations/build", response_model=BuildEscalationsResponse)
def build_escalations(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BuildEscalationsResponse:
    if db.get(Migration, migration_id) is None:
        raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

    service = EscalationService(db)
    created = service.build_mapping_reviews(migration_id)
    created.extend(service.build_for_migration(migration_id))
    db.commit()
    open_blocking = db.scalar(
        select(func.count(Escalation.id)).where(
            Escalation.migration_id == migration_id,
            Escalation.status == EscalationStatus.OPEN,
        )
    )
    return BuildEscalationsResponse(
        migration_id=migration_id,
        created=len(created),
        open_blocking=open_blocking or 0,
    )


@router.get("/migrations/{migration_id}/escalations", response_model=list[EscalationResponse])
def list_escalations(
    migration_id: str,
    status: EscalationStatus = Query(default=EscalationStatus.OPEN),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[EscalationResponse]:
    return EscalationService(db).list_for_user(migration_id, user, status)


@router.get("/escalations/{escalation_id}", response_model=EscalationResponse)
def get_escalation(
    escalation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EscalationResponse:
    return EscalationService(db).get_for_user(escalation_id, user)


@router.post("/escalations/{escalation_id}/resolve", response_model=EscalationResponse)
def resolve_escalation(
    escalation_id: str,
    request: ResolveEscalationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EscalationResponse:
    return EscalationService(db).resolve(escalation_id, request, user)
