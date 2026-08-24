from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.enums import AuditActorType, EscalationStatus, MigrationStatus
from app.core.errors import AppError
from app.graph.runner import MigrationGraphRunner
from app.models.canonical_record import CanonicalRecord
from app.models.escalation import Escalation
from app.models.mapping import Mapping
from app.models.migration import Migration
from app.models.push_attempt import PushAttempt
from app.models.user import User
from app.schemas.audit import AuditEventCreate
from app.services.audit import AuditService


@dataclass(frozen=True)
class WorkflowRunResult:
    migration_id: str
    status: MigrationStatus
    current_node: str | None
    mappings: int
    records: int
    open_reviews: int
    pushed: int
    failed: int


class MigrationWorkflowService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AuditService(db)

    def start(self, migration_id: str, user: User) -> WorkflowRunResult:
        migration = self.db.get(Migration, migration_id)
        if migration is None:
            raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

        if migration.status in {
            MigrationStatus.COMPLETED,
            MigrationStatus.PARTIALLY_COMPLETED,
            MigrationStatus.ROLLED_BACK,
            MigrationStatus.CANCELLED,
            MigrationStatus.WAITING_FOR_REVIEW,
        }:
            return self._result(migration)

        self._append_workflow_event(migration_id, user, "WORKFLOW_STARTED", "start_migration")
        MigrationGraphRunner(self.db, self.settings).start(migration_id, user)
        self.db.flush()
        self.db.refresh(migration)
        return self._result(migration)

    def _result(self, migration: Migration) -> WorkflowRunResult:
        return WorkflowRunResult(
            migration_id=migration.id,
            status=migration.status,
            current_node=migration.current_node,
            mappings=self._mapping_count(migration.id),
            records=self._record_count(migration.id),
            open_reviews=self._open_review_count(migration.id),
            pushed=self._push_count(migration.id),
            failed=self._failed_push_count(migration.id),
        )

    def _append_workflow_event(
        self,
        migration_id: str,
        user: User,
        event_type: str,
        current_node: str,
    ) -> None:
        self.audit.append(
            AuditEventCreate(
                migration_id=migration_id,
                actor_type=AuditActorType.SYSTEM,
                actor_id=user.id,
                event_type=event_type,
                entity_type="migration",
                entity_id=migration_id,
                metadata={"current_node": current_node},
            )
        )

    def _has_open_reviews(self, migration_id: str) -> bool:
        return self._open_review_count(migration_id) > 0

    def _open_review_count(self, migration_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count(Escalation.id)).where(
                    Escalation.migration_id == migration_id,
                    Escalation.status == EscalationStatus.OPEN,
                )
            )
            or 0
        )

    def _mapping_count(self, migration_id: str) -> int:
        return int(
            self.db.scalar(select(func.count(Mapping.id)).where(Mapping.migration_id == migration_id))
            or 0
        )

    def _record_count(self, migration_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count(CanonicalRecord.id)).where(
                    CanonicalRecord.migration_id == migration_id
                )
            )
            or 0
        )

    def _push_count(self, migration_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count(PushAttempt.id)).where(
                    PushAttempt.migration_id == migration_id,
                    PushAttempt.status == "SUCCEEDED",
                )
            )
            or 0
        )

    def _failed_push_count(self, migration_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count(PushAttempt.id)).where(
                    PushAttempt.migration_id == migration_id,
                    PushAttempt.status.in_(["FAILED_RETRYABLE", "FAILED_PERMANENT"]),
                )
            )
            or 0
        )
