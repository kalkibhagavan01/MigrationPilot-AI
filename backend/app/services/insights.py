import json
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.enums import EscalationStatus, MappingDecision, PushStatus, ValidationStatus
from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.canonical_record import CanonicalRecord
from app.models.escalation import Escalation
from app.models.mapping import Mapping
from app.models.migration import Migration
from app.models.mock_target import MockTargetRecord
from app.models.push_attempt import PushAttempt
from app.schemas.insights import (
    LLMUsageSummary,
    PushPreviewRecord,
    PushPreviewResponse,
    RollbackPreviewRecord,
    RollbackPreviewResponse,
    RunMetricsResponse,
    StageDuration,
)
from app.services.masking import mask_sensitive_payload, masked_field_names


class MigrationInsightsService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings

    def push_preview(self, migration_id: str) -> PushPreviewResponse:
        self._require_migration(migration_id)
        records = self._records(migration_id)
        latest_pushes = self._latest_pushes(migration_id)
        open_review_count = self._open_review_count(migration_id)

        preview_records: list[PushPreviewRecord] = []
        for record in records:
            data = json.loads(record.data_json)
            latest_push = latest_pushes.get(record.id)
            if latest_push and latest_push.status == PushStatus.SUCCEEDED:
                status = "ALREADY_PUSHED"
                action = "No change"
                reason = "This employee already reached the target for this migration."
            elif open_review_count > 0:
                status = "BLOCKED"
                action = "Wait"
                reason = "Open review items must be resolved before target push."
            elif record.validation_status == ValidationStatus.VALID:
                status = "READY"
                action = "Create target employee"
                reason = "Record passed validation and has no open review blocker."
            else:
                status = "BLOCKED"
                action = "Do not push"
                reason = _blocked_reason(record)

            preview_records.append(
                PushPreviewRecord(
                    record_id=record.id,
                    employee_id=record.employee_id,
                    status=status,
                    action=action,
                    reason=reason,
                    data=mask_sensitive_payload(data),
                )
            )

        ready_count = sum(1 for item in preview_records if item.status == "READY")
        return PushPreviewResponse(
            migration_id=migration_id,
            ready_count=ready_count,
            blocked_count=sum(1 for item in preview_records if item.status == "BLOCKED"),
            records=preview_records,
        )

    def rollback_preview(self, migration_id: str) -> RollbackPreviewResponse:
        self._require_migration(migration_id)
        attempts = self.db.scalars(
            select(PushAttempt)
            .where(
                PushAttempt.migration_id == migration_id,
                PushAttempt.status == PushStatus.SUCCEEDED,
                PushAttempt.target_record_id.is_not(None),
            )
            .order_by(PushAttempt.created_at)
        ).all()
        latest_by_target: dict[str, PushAttempt] = {}
        for attempt in attempts:
            if attempt.target_record_id:
                latest_by_target[attempt.target_record_id] = attempt

        rows: list[RollbackPreviewRecord] = []
        for target_record_id, attempt in latest_by_target.items():
            target = self.db.get(MockTargetRecord, target_record_id)
            if target is None or target.is_deleted:
                continue
            payload = json.loads(target.data_json)
            rows.append(
                RollbackPreviewRecord(
                    push_id=attempt.id,
                    target_record_id=target_record_id,
                    employee_id=target.employee_id,
                    action="Remove target employee",
                    data=mask_sensitive_payload(payload),
                )
            )
        return RollbackPreviewResponse(migration_id=migration_id, removable_count=len(rows), records=rows)

    def run_metrics(self, migration_id: str) -> RunMetricsResponse:
        migration = self._require_migration(migration_id)
        records = self._records(migration_id)
        mappings = self.db.scalars(select(Mapping).where(Mapping.migration_id == migration_id)).all()
        latest_pushes = self._latest_pushes(migration_id)
        audit_events = self.db.scalars(
            select(AuditEvent).where(AuditEvent.migration_id == migration_id).order_by(AuditEvent.created_at)
        ).all()

        valid_records = sum(1 for record in records if record.validation_status == ValidationStatus.VALID)
        invalid_records = sum(1 for record in records if record.validation_status == ValidationStatus.INVALID)
        review_records = sum(1 for record in records if record.validation_status == ValidationStatus.NEEDS_REVIEW)
        open_reviews = self._open_review_count(migration_id)
        pushed_records = sum(1 for push in latest_pushes.values() if push.status == PushStatus.SUCCEEDED)
        failed_pushes = sum(1 for push in latest_pushes.values() if str(push.status).startswith("FAILED"))
        already_pushed = {record_id for record_id, push in latest_pushes.items() if push.status == PushStatus.SUCCEEDED}
        ready_to_push = sum(
            1
            for record in records
            if record.validation_status == ValidationStatus.VALID and record.id not in already_pushed and open_reviews == 0
        )
        blocked_from_push = max(0, len(records) - ready_to_push - len(already_pushed))

        mapping_scores = [mapping.final_score for mapping in mappings]
        average_mapping_score = mean(mapping_scores) if mapping_scores else 0.0
        autonomous_mappings = sum(1 for mapping in mappings if mapping.decision == MappingDecision.AUTO_APPROVED)
        review_mappings = sum(1 for mapping in mappings if mapping.decision == MappingDecision.NEEDS_REVIEW)
        canonical_count = len(records)
        validation_ratio = valid_records / canonical_count if canonical_count else 0.0
        autonomy_ratio = autonomous_mappings / len(mappings) if mappings else 0.0
        push_success_rate = _push_success_rate(latest_pushes)
        push_component = 1.0 if push_success_rate is None else push_success_rate / 100

        readiness_score = _clamp_score(
            (valid_records / canonical_count * 100 if canonical_count else 0)
            - min(45, open_reviews * 8 + invalid_records * 12 + review_records * 8 + failed_pushes * 6)
        )
        agent_score = _clamp_score(
            (average_mapping_score * 40)
            + (validation_ratio * 35)
            + (autonomy_ratio * 15)
            + (push_component * 10)
            - min(35, open_reviews * 3 + invalid_records * 5 + failed_pushes * 4)
        )

        first_time = migration.created_at or (audit_events[0].created_at if audit_events else None)
        last_time = migration.updated_at if _is_terminal_status(str(migration.status)) else datetime.now(UTC)
        elapsed_seconds = _seconds_between(first_time, last_time) if first_time else None

        return RunMetricsResponse(
            migration_id=migration_id,
            readiness_score=readiness_score,
            agent_score=agent_score,
            elapsed_seconds=elapsed_seconds,
            stage_durations=_stage_durations(audit_events),
            total_records=migration.total_records,
            canonical_records=canonical_count,
            valid_records=valid_records,
            invalid_records=invalid_records,
            review_records=review_records,
            open_reviews=open_reviews,
            ready_to_push=ready_to_push,
            blocked_from_push=blocked_from_push,
            pushed_records=pushed_records,
            failed_pushes=failed_pushes,
            push_success_rate=push_success_rate,
            autonomous_mappings=autonomous_mappings,
            review_mappings=review_mappings,
            issue_counts=_issue_counts(records),
            sensitive_fields_masked=_sensitive_fields(records),
            llm=_llm_usage(mappings, audit_events, self.settings),
        )

    def _require_migration(self, migration_id: str) -> Migration:
        migration = self.db.get(Migration, migration_id)
        if migration is None:
            raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)
        return migration

    def _records(self, migration_id: str) -> list[CanonicalRecord]:
        return list(
            self.db.scalars(
                select(CanonicalRecord)
                .where(CanonicalRecord.migration_id == migration_id)
                .order_by(CanonicalRecord.employee_id)
            ).all()
        )

    def _open_review_count(self, migration_id: str) -> int:
        return self.db.scalar(
            select(func.count(Escalation.id)).where(
                Escalation.migration_id == migration_id,
                Escalation.status == EscalationStatus.OPEN,
            )
        ) or 0

    def _latest_pushes(self, migration_id: str) -> dict[str, PushAttempt]:
        attempts = self.db.scalars(
            select(PushAttempt)
            .where(PushAttempt.migration_id == migration_id)
            .order_by(PushAttempt.created_at)
        ).all()
        latest: dict[str, PushAttempt] = {}
        for attempt in attempts:
            latest[attempt.record_id] = attempt
        return latest


def _blocked_reason(record: CanonicalRecord) -> str:
    issues = json.loads(record.issues_json or "[]")
    if not issues:
        return "Record did not pass target validation."
    first = issues[0]
    issue_type = str(first.get("type") or "issue").replace("_", " ").lower()
    field = first.get("field")
    if field:
        return f"{field} has an unresolved {issue_type}."
    return f"Record has an unresolved {issue_type}."


def _push_success_rate(latest_pushes: dict[str, PushAttempt]) -> int | None:
    if not latest_pushes:
        return None
    succeeded = sum(1 for push in latest_pushes.values() if push.status == PushStatus.SUCCEEDED)
    return round(succeeded / len(latest_pushes) * 100)


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _is_terminal_status(status: str) -> bool:
    return status in {"COMPLETED", "PARTIALLY_COMPLETED", "ROLLED_BACK", "CANCELLED"}


def _seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(0.0, round((end - start).total_seconds(), 2))


def _stage_durations(events: list[AuditEvent]) -> list[StageDuration]:
    stages = [
        ("Upload and profile", "FILE_INGESTED", "FILE_PROFILED"),
        ("Mapping", "WORKFLOW_STARTED", "MAPPING_AUTO_APPROVED"),
        ("Human review", "MAPPING_ESCALATED", "REVIEW_RESOLVED"),
        ("Target push", "TARGET_PUSH_ATTEMPT", "RECORD_PUSHED"),
        ("Rollback", "RECORD_PUSHED", "ROLLBACK_EXECUTED"),
    ]
    by_type: dict[str, list[AuditEvent]] = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)
    durations: list[StageDuration] = []
    for label, start_type, end_type in stages:
        start = by_type.get(start_type, [None])[0]
        end = by_type.get(end_type, [None])[-1]
        durations.append(
            StageDuration(
                stage=label,
                seconds=_seconds_between(start.created_at if start else None, end.created_at if end else None),
            )
        )
    return durations


def _issue_counts(records: list[CanonicalRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for issue in json.loads(record.issues_json or "[]"):
            label = str(issue.get("type") or "issue")
            counts[label] = counts.get(label, 0) + 1
    return counts


def _sensitive_fields(records: list[CanonicalRecord]) -> list[str]:
    fields: set[str] = set()
    for record in records:
        fields.update(masked_field_names(json.loads(record.data_json)))
    return sorted(fields)


def _llm_usage(
    mappings: list[Mapping],
    events: list[AuditEvent],
    settings: Settings | None,
) -> LLMUsageSummary:
    llm_mappings = [mapping for mapping in mappings if mapping.decision_source == "LLM"]
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    has_usage = False
    for event in events:
        metadata = json.loads(event.metadata_json) if event.metadata_json else {}
        usage = metadata.get("usage") if isinstance(metadata, dict) else None
        if not isinstance(usage, dict):
            continue
        has_usage = True
        for key in usage_totals:
            value = usage.get(key)
            if isinstance(value, int):
                usage_totals[key] += value

    return LLMUsageSummary(
        used=bool(llm_mappings),
        provider="NVIDIA" if llm_mappings else None,
        model=settings.nvidia_model if settings and llm_mappings else None,
        prompt_tokens=usage_totals["prompt_tokens"] if has_usage else None,
        completion_tokens=usage_totals["completion_tokens"] if has_usage else None,
        total_tokens=usage_totals["total_tokens"] if has_usage else None,
    )
