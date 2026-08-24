from app.core.enums import PushStatus
from pydantic import BaseModel


class MockTargetEmployeeRequest(BaseModel):
    employee_id: str
    full_name: str
    email: str
    joining_date: str


class MockTargetEmployeeResponse(BaseModel):
    target_record_id: str
    status: str


class PushResultItem(BaseModel):
    record_id: str
    employee_id: str | None
    status: PushStatus
    target_record_id: str | None
    attempts: int
    http_status: int | None
    error_code: str | None = None


class PushMigrationResponse(BaseModel):
    migration_id: str
    pushed: int
    failed: int
    results: list[PushResultItem]


class RollbackResultItem(BaseModel):
    push_id: str
    target_record_id: str | None
    status: PushStatus


class RollbackMigrationResponse(BaseModel):
    migration_id: str
    rolled_back: int
    results: list[RollbackResultItem]
