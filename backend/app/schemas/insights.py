from typing import Any

from pydantic import BaseModel


class PushPreviewRecord(BaseModel):
    record_id: str
    employee_id: str | None
    status: str
    action: str
    reason: str
    data: dict[str, Any]


class PushPreviewResponse(BaseModel):
    migration_id: str
    ready_count: int
    blocked_count: int
    records: list[PushPreviewRecord]


class RollbackPreviewRecord(BaseModel):
    push_id: str
    target_record_id: str
    employee_id: str | None
    action: str
    data: dict[str, Any]


class RollbackPreviewResponse(BaseModel):
    migration_id: str
    removable_count: int
    records: list[RollbackPreviewRecord]


class StageDuration(BaseModel):
    stage: str
    seconds: float | None


class LLMUsageSummary(BaseModel):
    used: bool
    provider: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class RunMetricsResponse(BaseModel):
    migration_id: str
    readiness_score: int
    agent_score: int
    elapsed_seconds: float | None
    stage_durations: list[StageDuration]
    total_records: int
    canonical_records: int
    valid_records: int
    invalid_records: int
    review_records: int
    open_reviews: int
    ready_to_push: int
    blocked_from_push: int
    pushed_records: int
    failed_pushes: int
    push_success_rate: int | None
    autonomous_mappings: int
    review_mappings: int
    issue_counts: dict[str, int]
    sensitive_fields_masked: list[str]
    llm: LLMUsageSummary
