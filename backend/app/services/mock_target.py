import json
from hashlib import sha1
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mock_target import MockTargetFailure, MockTargetRecord


@dataclass(frozen=True)
class MockTargetResult:
    http_status: int
    target_record_id: str | None
    error_code: str | None = None
    error_message: str | None = None


class MockTargetService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_employee(self, idempotency_key: str, payload: dict[str, object]) -> MockTargetResult:
        existing = self.db.scalar(
            select(MockTargetRecord).where(MockTargetRecord.idempotency_key == idempotency_key)
        )
        if existing and not existing.is_deleted:
            return MockTargetResult(http_status=200, target_record_id=existing.target_record_id)

        employee_id = str(payload.get("employee_id", ""))
        if employee_id == "E-FAIL-422":
            return MockTargetResult(
                http_status=422,
                target_record_id=None,
                error_code="TARGET_VALIDATION_FAILED",
                error_message="Synthetic permanent validation failure.",
            )

        if employee_id == "E-FAIL-503":
            failure = self.db.get(MockTargetFailure, idempotency_key)
            if failure is None:
                failure = MockTargetFailure(idempotency_key=idempotency_key, attempt_count=0)
                self.db.add(failure)
                self.db.flush()

            failure.attempt_count += 1
            self.db.flush()
            if failure.attempt_count <= 2:
                return MockTargetResult(
                    http_status=503,
                    target_record_id=None,
                    error_code="TARGET_UNAVAILABLE",
                    error_message="Synthetic retryable target outage.",
                )

        target_record_id = f"T-{employee_id}-{sha1(idempotency_key.encode()).hexdigest()[:8]}"
        record = MockTargetRecord(
            target_record_id=target_record_id,
            idempotency_key=idempotency_key,
            employee_id=employee_id,
            data_json=json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True),
            is_deleted=False,
        )
        self.db.add(record)
        self.db.flush()
        return MockTargetResult(http_status=201, target_record_id=target_record_id)

    def delete_employee(self, target_record_id: str) -> MockTargetResult:
        record = self.db.get(MockTargetRecord, target_record_id)
        if record is None or record.is_deleted:
            return MockTargetResult(http_status=404, target_record_id=target_record_id)

        record.is_deleted = True
        self.db.flush()
        return MockTargetResult(http_status=204, target_record_id=target_record_id)
