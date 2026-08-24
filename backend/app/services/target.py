import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import PERMANENT_TARGET_STATUSES, RETRYABLE_TARGET_STATUSES
from app.core.enums import AuditActorType, MigrationStatus, PushStatus, ValidationStatus
from app.core.errors import AppError
from app.models.canonical_record import CanonicalRecord
from app.models.escalation import Escalation
from app.models.migration import Migration
from app.models.push_attempt import PushAttempt
from app.schemas.audit import AuditEventCreate
from app.schemas.target import PushResultItem, RollbackResultItem
from app.services.audit import AuditService
from app.services.mock_target import MockTargetResult, MockTargetService


class TargetIntegrationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.mock_target = MockTargetService(db)
        self.audit = AuditService(db)

    def push_migration(self, migration_id: str) -> list[PushResultItem]:
        migration = self.db.get(Migration, migration_id)
        if migration is None:
            raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

        if self._has_open_escalations(migration_id):
            raise AppError(
                "UNRESOLVED_BLOCKING_ESCALATIONS",
                "Resolve blocking escalations before pushing.",
                409,
            )

        records = self.db.scalars(
            select(CanonicalRecord).where(
                CanonicalRecord.migration_id == migration_id,
                CanonicalRecord.validation_status == ValidationStatus.VALID,
            )
        ).all()
        if not records:
            raise AppError("RECORDS_NOT_VALID", "No valid records are ready to push.", 409)

        migration.status = MigrationStatus.PUSHING
        migration.current_node = "push_records"
        results = [self.push_record(migration_id, record) for record in records]
        failed = [result for result in results if result.status != PushStatus.SUCCEEDED]
        migration.status = MigrationStatus.PARTIALLY_COMPLETED if failed else MigrationStatus.COMPLETED
        self.db.flush()
        return results

    def push_record(self, migration_id: str, record: CanonicalRecord) -> PushResultItem:
        employee_id = record.employee_id
        idempotency_key = f"{migration_id}:{employee_id}"
        payload = json.loads(record.data_json)
        last_attempt: PushAttempt | None = None

        for attempt_number in range(1, 4):
            target_result = self.mock_target.create_employee(idempotency_key, payload)
            status = _status_from_target_result(target_result)
            last_attempt = self._record_attempt(
                migration_id,
                record.id,
                idempotency_key,
                attempt_number,
                target_result,
                status,
            )
            if status == PushStatus.SUCCEEDED or target_result.http_status in PERMANENT_TARGET_STATUSES:
                break
            if target_result.http_status not in RETRYABLE_TARGET_STATUSES:
                break

        assert last_attempt is not None
        self.audit.append(
            AuditEventCreate(
                migration_id=migration_id,
                actor_type=AuditActorType.SYSTEM,
                event_type="RECORD_PUSHED"
                if last_attempt.status == PushStatus.SUCCEEDED
                else "RECORD_PUSH_FAILED",
                entity_type="canonical_record",
                entity_id=record.id,
                metadata={
                    "employee_id": employee_id,
                    "status": last_attempt.status,
                    "target_record_id": last_attempt.target_record_id,
                },
            )
        )
        return PushResultItem(
            record_id=record.id,
            employee_id=employee_id,
            status=last_attempt.status,
            target_record_id=last_attempt.target_record_id,
            attempts=last_attempt.attempt_number,
            http_status=last_attempt.http_status,
            error_code=last_attempt.error_code,
        )

    def rollback_migration(self, migration_id: str) -> list[RollbackResultItem]:
        succeeded = self.db.scalars(
            select(PushAttempt)
            .where(
                PushAttempt.migration_id == migration_id,
                PushAttempt.status == PushStatus.SUCCEEDED,
                PushAttempt.target_record_id.is_not(None),
            )
            .order_by(PushAttempt.created_at)
        ).all()
        latest_by_target: dict[str, PushAttempt] = {}
        for attempt in succeeded:
            if attempt.target_record_id:
                latest_by_target[attempt.target_record_id] = attempt

        results: list[RollbackResultItem] = []
        for attempt in latest_by_target.values():
            assert attempt.target_record_id is not None
            delete_result = self.mock_target.delete_employee(attempt.target_record_id)
            attempt.status = PushStatus.ROLLED_BACK
            results.append(
                RollbackResultItem(
                    push_id=attempt.id,
                    target_record_id=attempt.target_record_id,
                    status=PushStatus.ROLLED_BACK,
                )
            )
            self.audit.append(
                AuditEventCreate(
                    migration_id=migration_id,
                    actor_type=AuditActorType.SYSTEM,
                    event_type="ROLLBACK_EXECUTED",
                    entity_type="push_attempt",
                    entity_id=attempt.id,
                    metadata={
                        "target_record_id": attempt.target_record_id,
                        "http_status": delete_result.http_status,
                    },
                )
            )

        migration = self.db.get(Migration, migration_id)
        if migration:
            migration.status = MigrationStatus.ROLLED_BACK
            migration.current_node = "rollback_migration"
        self.db.flush()
        return results

    def retry_failed(self, migration_id: str) -> list[PushResultItem]:
        migration = self.db.get(Migration, migration_id)
        if migration is None:
            raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

        latest_by_record: dict[str, PushAttempt] = {}
        attempts = self.db.scalars(
            select(PushAttempt)
            .where(PushAttempt.migration_id == migration_id)
            .order_by(PushAttempt.created_at)
        ).all()
        for attempt in attempts:
            latest_by_record[attempt.record_id] = attempt

        retryable_record_ids = [
            record_id
            for record_id, attempt in latest_by_record.items()
            if attempt.status == PushStatus.FAILED_RETRYABLE
        ]
        if not retryable_record_ids:
            return []

        records = self.db.scalars(
            select(CanonicalRecord).where(CanonicalRecord.id.in_(retryable_record_ids))
        ).all()
        migration.status = MigrationStatus.PUSHING
        migration.current_node = "retry_failed_records"
        results = [self.push_record(migration_id, record) for record in records]
        failed = [result for result in results if result.status != PushStatus.SUCCEEDED]
        migration.status = MigrationStatus.PARTIALLY_COMPLETED if failed else MigrationStatus.COMPLETED
        self.db.flush()
        return results

    def _record_attempt(
        self,
        migration_id: str,
        record_id: str,
        idempotency_key: str,
        attempt_number: int,
        target_result: MockTargetResult,
        status: PushStatus,
    ) -> PushAttempt:
        attempt = PushAttempt(
            migration_id=migration_id,
            record_id=record_id,
            idempotency_key=idempotency_key,
            target_record_id=target_result.target_record_id,
            attempt_number=attempt_number,
            status=status,
            http_status=target_result.http_status,
            error_code=target_result.error_code,
            error_message=target_result.error_message,
        )
        self.db.add(attempt)
        self.db.flush()
        self.audit.append(
            AuditEventCreate(
                migration_id=migration_id,
                actor_type=AuditActorType.SYSTEM,
                event_type="TARGET_PUSH_ATTEMPT",
                entity_type="push_attempt",
                entity_id=attempt.id,
                metadata={
                    "record_id": record_id,
                    "attempt_number": attempt_number,
                    "status": status,
                    "http_status": target_result.http_status,
                    "error_code": target_result.error_code,
                    "target_record_id": target_result.target_record_id,
                },
            )
        )
        return attempt

    def _has_open_escalations(self, migration_id: str) -> bool:
        return (
            self.db.scalar(
                select(Escalation.id)
                .where(Escalation.migration_id == migration_id, Escalation.status == "OPEN")
                .limit(1)
            )
            is not None
        )


def _status_from_target_result(result: MockTargetResult) -> PushStatus:
    if result.http_status in {200, 201}:
        return PushStatus.SUCCEEDED
    if result.http_status in RETRYABLE_TARGET_STATUSES:
        return PushStatus.FAILED_RETRYABLE
    return PushStatus.FAILED_PERMANENT
