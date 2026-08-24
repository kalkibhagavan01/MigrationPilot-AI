from app.core.enums import ValidationStatus
from pydantic import BaseModel


class CanonicalRecordResponse(BaseModel):
    id: str
    employee_id: str | None
    validation_status: ValidationStatus
    issues: list[dict[str, object]]


class MigrationRecordResponse(CanonicalRecordResponse):
    data: dict[str, object]
    push_status: str | None = None
    target_record_id: str | None = None


class CanonicalizeResponse(BaseModel):
    migration_id: str
    records_created: int
    valid_records: int
    invalid_records: int
    review_records: int
    records: list[CanonicalRecordResponse]
