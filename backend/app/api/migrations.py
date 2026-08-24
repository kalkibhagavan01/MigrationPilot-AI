import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.enums import AuditActorType, MappingDecision, MigrationStatus
from app.core.errors import AppError
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.column_profile import ColumnProfile
from app.models.canonical_record import CanonicalRecord
from app.models.mapping import Mapping
from app.models.migration import Migration
from app.models.source_file import SourceFile
from app.models.user import User
from app.schemas.audit import AuditEventCreate
from app.schemas.canonical import (
    CanonicalizeResponse,
    CanonicalRecordResponse,
    MigrationRecordResponse,
)
from app.schemas.mapping import GenerateMappingsResponse, MappingResponseItem
from app.schemas.migration import (
    CreateMigrationResponse,
    MigrationProgress,
    MigrationSummary,
    StartMigrationResponse,
)
from app.schemas.insights import PushPreviewResponse, RollbackPreviewResponse, RunMetricsResponse
from app.schemas.target import PushMigrationResponse, RollbackMigrationResponse
from app.services.audit import AuditService, audit_event_response
from app.services.canonicalization import CanonicalizationService
from app.services.insights import MigrationInsightsService
from app.services.ingestion import IngestionService
from app.services.llm import NvidiaLLMProvider
from app.services.mapping import MappingService
from app.services.masking import mask_sensitive_payload
from app.services.ops import OpsService
from app.services.profiling import ProfilingService
from app.services.target import TargetIntegrationService
from app.services.workflow import MigrationWorkflowService

router = APIRouter(prefix="/migrations", tags=["migrations"])


@router.post("", response_model=CreateMigrationResponse, status_code=201)
async def create_migration(
    files: list[UploadFile] | None = File(default=None),
    target_schema_version: str = Form(default="employee-v1"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> CreateMigrationResponse:
    OpsService(db).enforce_kill_switch_open()
    migration = Migration(
        status=MigrationStatus.UPLOADING,
        created_by=user.id,
        target_schema_version=target_schema_version,
        current_node="ingest_files",
    )
    db.add(migration)
    db.flush()

    audit = AuditService(db)
    ingestion = IngestionService(db, settings.upload_storage_dir)
    profiling = ProfilingService(db)

    datasets = await ingestion.ingest(migration.id, files or [])
    profiles_created = 0
    for dataset in datasets:
        audit.append(
            AuditEventCreate(
                migration_id=migration.id,
                actor_type=AuditActorType.USER,
                actor_id=user.id,
                event_type="FILE_INGESTED",
                entity_type="source_file",
                entity_id=dataset.source_file.id,
                metadata={"file_name": dataset.source_file.original_name},
            )
        )
        profiles = profiling.profile_dataset(dataset.source_file, dataset.sheets)
        profiles_created += len(profiles)
        audit.append(
            AuditEventCreate(
                migration_id=migration.id,
                actor_type=AuditActorType.SYSTEM,
                event_type="FILE_PROFILED",
                entity_type="source_file",
                entity_id=dataset.source_file.id,
                metadata={"profiles": len(profiles)},
            )
        )

    migration.status = MigrationStatus.PROFILING
    migration.current_node = "profile_files"
    migration.total_records = sum(dataset.source_file.row_count or 0 for dataset in datasets)
    db.commit()

    return CreateMigrationResponse(
        migration_id=migration.id,
        status=migration.status,
        profiles_created=profiles_created,
        files=[
            {
                "id": dataset.source_file.id,
                "name": dataset.source_file.original_name,
                "size_bytes": dataset.source_file.size_bytes,
                "row_count": dataset.source_file.row_count,
            }
            for dataset in datasets
        ],
    )


@router.get("/{migration_id}", response_model=MigrationSummary)
def get_migration(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MigrationSummary:
    migration = db.get(Migration, migration_id)
    if migration is None:
        raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

    file_count = db.scalar(select(func.count(SourceFile.id)).where(SourceFile.migration_id == migration_id))
    profile_count = db.scalar(
        select(func.count(ColumnProfile.id))
        .join(SourceFile)
        .where(SourceFile.migration_id == migration_id)
    )
    return MigrationSummary(
        id=migration.id,
        status=migration.status,
        current_node=migration.current_node,
        target_schema_version=migration.target_schema_version,
        progress=MigrationProgress(
            files=file_count or 0,
            records=migration.total_records,
            profiles=profile_count or 0,
        ),
    )


@router.post("/{migration_id}/mappings", response_model=GenerateMappingsResponse)
def generate_mappings(
    migration_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> GenerateMappingsResponse:
    migration = db.get(Migration, migration_id)
    if migration is None:
        raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

    existing_mappings = db.scalars(
        select(Mapping).where(Mapping.migration_id == migration_id).order_by(Mapping.source_column)
    ).all()
    if existing_mappings:
        return GenerateMappingsResponse(
            migration_id=migration_id,
            mappings=[_mapping_response(mapping) for mapping in existing_mappings],
        )

    llm_provider = NvidiaLLMProvider(settings) if settings.nvidia_api_key.strip() else None
    service = MappingService(db, llm_provider=llm_provider)
    mappings = service.generate_for_migration(migration_id)
    audit = AuditService(db)
    for mapping in mappings:
        event_type = (
            "MAPPING_AUTO_APPROVED"
            if mapping.decision == MappingDecision.AUTO_APPROVED
            else "MAPPING_ESCALATED"
        )
        audit.append(
            AuditEventCreate(
                migration_id=migration_id,
                actor_type=AuditActorType.AGENT,
                actor_id=user.id,
                event_type=event_type,
                entity_type="mapping",
                entity_id=mapping.id,
                metadata={
                    "source_column": mapping.source_column,
                    "target_field": mapping.target_field,
                    "final_score": mapping.final_score,
                },
            )
        )

    migration.status = MigrationStatus.MAPPING
    migration.current_node = "generate_mapping_candidates"
    db.commit()
    return GenerateMappingsResponse(
        migration_id=migration_id,
        mappings=[_mapping_response(mapping) for mapping in mappings],
    )


def _mapping_response(mapping: Mapping) -> MappingResponseItem:
    return MappingResponseItem(
        id=mapping.id,
        source_column=mapping.source_column,
        target_field=mapping.target_field,
        semantic_score=mapping.semantic_score,
        name_score=mapping.name_score,
        type_score=mapping.type_score,
        value_score=mapping.value_score,
        final_score=mapping.final_score,
        decision=mapping.decision,
        reasoning=mapping.reasoning,
    )


@router.post("/{migration_id}/start", response_model=StartMigrationResponse)
def start_migration(
    migration_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> StartMigrationResponse:
    OpsService(db).enforce_kill_switch_open()
    result = MigrationWorkflowService(db, settings).start(migration_id, user)
    db.commit()
    return StartMigrationResponse(
        migration_id=result.migration_id,
        status=result.status,
        current_node=result.current_node,
        mappings=result.mappings,
        records=result.records,
        open_reviews=result.open_reviews,
        pushed=result.pushed,
        failed=result.failed,
    )


@router.post("/{migration_id}/canonicalize", response_model=CanonicalizeResponse)
def canonicalize_migration(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CanonicalizeResponse:
    migration = db.get(Migration, migration_id)
    if migration is None:
        raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

    records = CanonicalizationService(db).canonicalize(migration_id)
    valid_records = sum(1 for record in records if record.validation_status == "VALID")
    invalid_records = sum(1 for record in records if record.validation_status == "INVALID")
    review_records = sum(1 for record in records if record.validation_status == "NEEDS_REVIEW")

    migration.status = MigrationStatus.VALIDATING
    migration.current_node = "validate_records"
    migration.valid_records = valid_records
    migration.failed_records = invalid_records + review_records
    db.commit()

    return CanonicalizeResponse(
        migration_id=migration_id,
        records_created=len(records),
        valid_records=valid_records,
        invalid_records=invalid_records,
        review_records=review_records,
        records=[_canonical_response(record) for record in records],
    )


def _canonical_response(record: CanonicalRecord) -> CanonicalRecordResponse:
    return CanonicalRecordResponse(
        id=record.id,
        employee_id=record.employee_id,
        validation_status=record.validation_status,
        issues=json.loads(record.issues_json),
    )


@router.get("/{migration_id}/records", response_model=list[MigrationRecordResponse])
def list_records(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[MigrationRecordResponse]:
    if db.get(Migration, migration_id) is None:
        raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

    records = db.scalars(
        select(CanonicalRecord)
        .where(CanonicalRecord.migration_id == migration_id)
        .order_by(CanonicalRecord.employee_id)
    ).all()
    latest_pushes = _latest_pushes(db, migration_id)
    responses: list[MigrationRecordResponse] = []
    for record in records:
        push = latest_pushes.get(record.id)
        responses.append(
            MigrationRecordResponse(
                id=record.id,
                employee_id=record.employee_id,
                validation_status=record.validation_status,
                issues=json.loads(record.issues_json),
                data=mask_sensitive_payload(json.loads(record.data_json)),
                push_status=push.status if push else None,
                target_record_id=push.target_record_id if push else None,
            )
        )
    return responses


@router.get("/{migration_id}/push-preview", response_model=PushPreviewResponse)
def push_preview(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PushPreviewResponse:
    return MigrationInsightsService(db).push_preview(migration_id)


@router.get("/{migration_id}/rollback-preview", response_model=RollbackPreviewResponse)
def rollback_preview(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> RollbackPreviewResponse:
    return MigrationInsightsService(db).rollback_preview(migration_id)


@router.get("/{migration_id}/run-metrics", response_model=RunMetricsResponse)
def run_metrics(
    migration_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(get_current_user),
) -> RunMetricsResponse:
    return MigrationInsightsService(db, settings).run_metrics(migration_id)


@router.get("/{migration_id}/activity")
def list_activity(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, object]]:
    if db.get(Migration, migration_id) is None:
        raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

    return [
        {
            "id": event.id,
            "time": event.created_at,
            "message": _activity_message(event.event_type),
            "event_type": event.event_type,
            "details": mask_sensitive_payload(audit_event_response(event).metadata),
        }
        for event in AuditService(db).list_for_migration(migration_id)
    ]


@router.get("/{migration_id}/events")
def migration_events(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    migration = db.get(Migration, migration_id)
    if migration is None:
        raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

    payload = {
        "event_id": migration.id,
        "migration_id": migration.id,
        "type": "migration.status",
        "payload": {
            "status": migration.status,
            "current_node": migration.current_node,
            "records": migration.total_records,
            "valid_records": migration.valid_records,
        },
    }

    def stream():
        yield f"event: migration.status\ndata: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


def _latest_pushes(db: Session, migration_id: str):
    from app.models.push_attempt import PushAttempt

    attempts = db.scalars(
        select(PushAttempt)
        .where(PushAttempt.migration_id == migration_id)
        .order_by(PushAttempt.created_at)
    ).all()
    latest = {}
    for attempt in attempts:
        latest[attempt.record_id] = attempt
    return latest


def _activity_message(event_type: str) -> str:
    messages = {
        "FILE_INGESTED": "Loaded source file",
        "FILE_PROFILED": "Analyzed source columns",
        "WORKFLOW_STARTED": "Started migration workflow",
        "MAPPING_AUTO_APPROVED": "Automatically matched a field",
        "MAPPING_ESCALATED": "Field mapping needs review",
        "VALUE_TRANSFORM_ISSUE": "Found a value that needs attention",
        "CONFLICT_RESOLVED_BY_PRECEDENCE": "Resolved a source conflict using precedence rules",
        "EXACT_DUPLICATE_REMOVED": "Removed an exact duplicate",
        "REVIEW_RESOLVED": "Review item resolved",
        "REVIEW_SENT_TO_HR": "Review item sent to HR",
        "RECORD_PUSHED": "Pushed record to target",
        "RECORD_PUSH_FAILED": "Target push failed",
        "ROLLBACK_EXECUTED": "Rolled back target record",
    }
    return messages.get(event_type, event_type.replace("_", " ").title())


@router.post("/{migration_id}/push", response_model=PushMigrationResponse)
def push_migration(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PushMigrationResponse:
    OpsService(db).enforce_kill_switch_open()
    results = TargetIntegrationService(db).push_migration(migration_id)
    db.commit()
    failed = [result for result in results if result.status != "SUCCEEDED"]
    return PushMigrationResponse(
        migration_id=migration_id,
        pushed=len(results) - len(failed),
        failed=len(failed),
        results=results,
    )


@router.post("/{migration_id}/retry-failed", response_model=PushMigrationResponse)
def retry_failed_migration(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PushMigrationResponse:
    OpsService(db).enforce_kill_switch_open()
    results = TargetIntegrationService(db).retry_failed(migration_id)
    db.commit()
    failed = [result for result in results if result.status != "SUCCEEDED"]
    return PushMigrationResponse(
        migration_id=migration_id,
        pushed=len(results) - len(failed),
        failed=len(failed),
        results=results,
    )


@router.post("/{migration_id}/rollback", response_model=RollbackMigrationResponse)
def rollback_migration(
    migration_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> RollbackMigrationResponse:
    results = TargetIntegrationService(db).rollback_migration(migration_id)
    db.commit()
    return RollbackMigrationResponse(
        migration_id=migration_id,
        rolled_back=len(results),
        results=results,
    )
