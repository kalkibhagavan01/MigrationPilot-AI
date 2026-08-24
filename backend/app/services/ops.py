import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import EscalationStatus, PushStatus
from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.escalation import Escalation
from app.models.migration import Migration
from app.models.push_attempt import PushAttempt
from app.models.system_state import SystemState
from app.schemas.ops import KillSwitchStatus, OpsMetrics

KILL_SWITCH_KEY = "kill_switch"


class OpsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def kill_switch_status(self) -> KillSwitchStatus:
        state = self.db.get(SystemState, KILL_SWITCH_KEY)
        if state is None:
            return KillSwitchStatus(enabled=False)
        payload = json.loads(state.value)
        return KillSwitchStatus(
            enabled=bool(payload.get("enabled")),
            reason=payload.get("reason") if isinstance(payload.get("reason"), str) else None,
        )

    def set_kill_switch(self, enabled: bool, reason: str | None) -> KillSwitchStatus:
        payload = {"enabled": enabled, "reason": reason}
        state = self.db.get(SystemState, KILL_SWITCH_KEY)
        if state is None:
            state = SystemState(key=KILL_SWITCH_KEY, value=json.dumps(payload))
            self.db.add(state)
        else:
            state.value = json.dumps(payload)
        self.db.commit()
        return KillSwitchStatus(enabled=enabled, reason=reason)

    def enforce_kill_switch_open(self) -> None:
        status = self.kill_switch_status()
        if status.enabled:
            raise AppError(
                "KILL_SWITCH_ACTIVE",
                "Kill switch is active. New starts and target pushes are disabled.",
                423,
                {"reason": status.reason},
            )

    def metrics(self) -> OpsMetrics:
        failed_statuses = [PushStatus.FAILED_PERMANENT, PushStatus.FAILED_RETRYABLE]
        return OpsMetrics(
            migrations=self.db.scalar(select(func.count(Migration.id))) or 0,
            audit_events=self.db.scalar(select(func.count(AuditEvent.id))) or 0,
            open_escalations=self.db.scalar(
                select(func.count(Escalation.id)).where(Escalation.status == EscalationStatus.OPEN)
            )
            or 0,
            pushed_records=self.db.scalar(
                select(func.count(PushAttempt.id)).where(PushAttempt.status == PushStatus.SUCCEEDED)
            )
            or 0,
            failed_pushes=self.db.scalar(
                select(func.count(PushAttempt.id)).where(PushAttempt.status.in_(failed_statuses))
            )
            or 0,
            kill_switch_enabled=self.kill_switch_status().enabled,
        )
