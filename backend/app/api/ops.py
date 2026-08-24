from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.db.session import get_db
from app.dependencies import get_current_user, require_roles
from app.models.user import User
from app.schemas.ops import KillSwitchStatus, KillSwitchUpdate, OpsMetrics
from app.services.ops import OpsService

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/health")
def health(_: User = Depends(get_current_user)) -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics", response_model=OpsMetrics)
def metrics(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> OpsMetrics:
    return OpsService(db).metrics()


@router.get("/kill-switch", response_model=KillSwitchStatus)
def kill_switch_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> KillSwitchStatus:
    return OpsService(db).kill_switch_status()


@router.put("/kill-switch", response_model=KillSwitchStatus)
def update_kill_switch(
    payload: KillSwitchUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.SYSTEM_ADMIN)),
) -> KillSwitchStatus:
    return OpsService(db).set_kill_switch(payload.enabled, payload.reason)
