from app.core.enums import MigrationStatus
from pydantic import BaseModel


class UploadedFileSummary(BaseModel):
    id: str
    name: str
    size_bytes: int
    row_count: int | None


class MigrationProgress(BaseModel):
    files: int
    records: int
    profiles: int


class MigrationSummary(BaseModel):
    id: str
    status: MigrationStatus
    current_node: str | None
    target_schema_version: str
    progress: MigrationProgress


class CreateMigrationResponse(BaseModel):
    migration_id: str
    status: MigrationStatus
    files: list[UploadedFileSummary]
    profiles_created: int


class StartMigrationResponse(BaseModel):
    migration_id: str
    status: MigrationStatus
    current_node: str | None
    mappings: int
    records: int
    open_reviews: int
    pushed: int
    failed: int
