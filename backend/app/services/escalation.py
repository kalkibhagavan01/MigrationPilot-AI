import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.constants import TARGET_FIELD_TYPES
from app.core.enums import (
    AuditActorType,
    DataClassification,
    EscalationStatus,
    MappingDecision,
    MigrationStatus,
    Severity,
    UserRole,
    ValidationStatus,
)
from app.core.errors import AppError
from app.models.canonical_record import CanonicalRecord
from app.models.escalation import Escalation
from app.models.mapping import Mapping
from app.models.migration import Migration
from app.models.user import User
from app.schemas.audit import AuditEventCreate
from app.schemas.escalation import EscalationResponse, ResolveEscalationRequest
from app.services.audit import AuditService
from app.services.cleaning import clean_value
from app.services.policy import PolicyService, mask_sensitive_context
from app.services.validation import ValidationService


class EscalationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.policy = PolicyService()
        self.audit = AuditService(db)

    def build_for_migration(self, migration_id: str) -> list[Escalation]:
        records = self.db.scalars(
            select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id)
        ).all()
        existing_keys = self._existing_issue_keys(migration_id)
        created: list[Escalation] = []
        for record in records:
            data = json.loads(record.data_json)
            provenance = json.loads(record.provenance_json)
            for issue in json.loads(record.issues_json):
                issue_key = _issue_key(record.id, issue)
                if issue_key in existing_keys:
                    continue
                policy = self.policy.classify_issue(issue)
                context = _review_context(record, data, provenance, issue)
                escalation = Escalation(
                    migration_id=migration_id,
                    record_id=record.id,
                    issue_type=str(issue.get("type", "UNKNOWN")),
                    severity=policy.severity,
                    classification=policy.classification,
                    required_role=policy.required_role,
                    status=EscalationStatus.OPEN,
                    payload_json=_dump_json(context),
                    recommended_action_json=_dump_json({"action": "REVIEW_AND_RESOLVE"}),
                )
                self.db.add(escalation)
                created.append(escalation)
                existing_keys.add(issue_key)

        if created:
            migration = self.db.get(Migration, migration_id)
            if migration:
                migration.status = MigrationStatus.WAITING_FOR_REVIEW
                migration.current_node = "create_record_escalations"
        self.db.flush()
        return created

    def build_mapping_reviews(self, migration_id: str) -> list[Escalation]:
        mappings = self.db.scalars(
            select(Mapping)
            .where(
                Mapping.migration_id == migration_id,
                Mapping.decision.in_([MappingDecision.NEEDS_REVIEW, MappingDecision.BLOCKED]),
            )
            .order_by(Mapping.source_column)
        ).all()
        existing_mapping_ids = self._existing_mapping_review_ids(migration_id)
        created: list[Escalation] = []
        for mapping in mappings:
            if mapping.id in existing_mapping_ids:
                continue
            context = _mapping_review_context(mapping)
            escalation = Escalation(
                migration_id=migration_id,
                record_id=None,
                issue_type="MAPPING_AMBIGUITY"
                if mapping.decision == MappingDecision.NEEDS_REVIEW
                else "MAPPING_BLOCKED",
                severity=Severity.MEDIUM
                if mapping.decision == MappingDecision.NEEDS_REVIEW
                else Severity.HIGH,
                classification=DataClassification.INTERNAL,
                required_role=UserRole.IMPLEMENTATION_CONSULTANT,
                status=EscalationStatus.OPEN,
                payload_json=_dump_json(context),
                recommended_action_json=_dump_json({"action": "REVIEW_MAPPING"}),
            )
            self.db.add(escalation)
            created.append(escalation)

        if created:
            migration = self.db.get(Migration, migration_id)
            if migration:
                migration.status = MigrationStatus.WAITING_FOR_REVIEW
                migration.current_node = "review_mapping_escalations"
        self.db.flush()
        return created

    def list_for_user(
        self,
        migration_id: str,
        user: User,
        status: EscalationStatus = EscalationStatus.OPEN,
    ) -> list[EscalationResponse]:
        escalations = self.db.scalars(
            select(Escalation)
            .where(Escalation.migration_id == migration_id, Escalation.status == status)
            .order_by(Escalation.created_at)
        ).all()
        return [
            self.to_response(escalation, user)
            for escalation in escalations
            if self.policy.can_see_queue_item(user, escalation.required_role)
        ]

    def get_for_user(self, escalation_id: str, user: User) -> EscalationResponse:
        escalation = self.db.get(Escalation, escalation_id)
        if escalation is None:
            raise AppError("ESCALATION_NOT_FOUND", "Escalation was not found.", 404)
        if not self.policy.can_see_queue_item(user, escalation.required_role):
            raise AppError("INSUFFICIENT_REVIEW_ROLE", "User cannot view this escalation.", 403)
        return self.to_response(escalation, user)

    def resolve(
        self,
        escalation_id: str,
        request: ResolveEscalationRequest,
        user: User,
    ) -> EscalationResponse:
        escalation = self.db.get(Escalation, escalation_id)
        if escalation is None:
            raise AppError("ESCALATION_NOT_FOUND", "Escalation was not found.", 404)
        if not self.policy.can_resolve(user, escalation.required_role):
            raise AppError("INSUFFICIENT_REVIEW_ROLE", "User cannot resolve this escalation.", 403)

        if _is_mapping_escalation(escalation):
            self._apply_mapping_resolution(escalation, request, user)
        elif request.action == "CORRECT":
            self._apply_correction(escalation, request)
        elif request.action == "APPROVE":
            self._apply_approval(escalation)
        elif request.action == "SEND_TO_HR":
            self.audit.append(
                AuditEventCreate(
                    migration_id=escalation.migration_id,
                    actor_type=AuditActorType.USER,
                    actor_id=user.id,
                    event_type="REVIEW_SENT_TO_HR",
                    entity_type="escalation",
                    entity_id=escalation.id,
                    metadata={
                        **request.resolution,
                        "executed_by": user.username,
                        "action": request.action,
                    },
                )
            )
            self.db.commit()
            return self.to_response(escalation, user)

        status = EscalationStatus.RESOLVED if request.action != "REJECT" else EscalationStatus.REJECTED
        result = self.db.execute(
            update(Escalation)
            .where(Escalation.id == escalation_id, Escalation.status == EscalationStatus.OPEN)
            .values(
                status=status,
                resolved_at=datetime.now(UTC).isoformat(),
                resolved_by=user.id,
                resolution_json=_dump_json(request.model_dump()),
            )
        )
        if result.rowcount != 1:
            raise AppError("ESCALATION_ALREADY_RESOLVED", "Escalation is already resolved.", 409)

        self.audit.append(
            AuditEventCreate(
                migration_id=escalation.migration_id,
                actor_type=AuditActorType.USER,
                actor_id=user.id,
                event_type="REVIEW_RESOLVED",
                entity_type="escalation",
                entity_id=escalation.id,
                metadata={
                    "action": request.action,
                    "resolution": request.resolution,
                    "comment": request.comment,
                    "issue_type": escalation.issue_type,
                    "executed_by": user.username,
                    "executed_by_user_id": user.id,
                },
            )
        )
        self._resume_if_clear(escalation, request, user)
        self.db.commit()
        self.db.refresh(escalation)
        return self.to_response(escalation, user)

    def to_response(self, escalation: Escalation, user: User) -> EscalationResponse:
        context = json.loads(escalation.payload_json)
        if not self.policy.can_view_raw(user, escalation.required_role):
            context = mask_sensitive_context(context)

        return EscalationResponse(
            id=escalation.id,
            migration_id=escalation.migration_id,
            record_id=escalation.record_id,
            issue_type=escalation.issue_type,
            severity=escalation.severity,
            classification=escalation.classification,
            required_role=escalation.required_role,
            status=escalation.status,
            context=context,
            recommended_action=json.loads(escalation.recommended_action_json)
            if escalation.recommended_action_json
            else None,
        )

    def _resume_if_clear(
        self,
        escalation: Escalation,
        request: ResolveEscalationRequest,
        user: User,
    ) -> None:
        open_count = self.db.scalar(
            select(Escalation.id)
            .where(
                Escalation.migration_id == escalation.migration_id,
                Escalation.status == EscalationStatus.OPEN,
            )
            .limit(1)
        )
        if open_count is not None:
            return
        migration = self.db.get(Migration, escalation.migration_id)
        if migration is None or migration.status != MigrationStatus.WAITING_FOR_REVIEW:
            return
        if migration.current_node not in {"mapping_review_gate_node", "data_review_gate_node"}:
            migration.status = MigrationStatus.VALIDATING
            migration.current_node = "validate_records"
            return

        from app.graph.runner import MigrationGraphRunner

        MigrationGraphRunner(self.db, get_settings()).resume(
            escalation.migration_id,
            user,
            {
                "decision_id": escalation.id,
                "escalation_id": escalation.id,
                "action": request.action,
                "issue_type": escalation.issue_type,
            },
        )

    def _apply_correction(
        self,
        escalation: Escalation,
        request: ResolveEscalationRequest,
    ) -> None:
        if escalation.record_id is None:
            raise AppError("CORRECTION_NOT_APPLICABLE", "This review item has no record to correct.", 400)

        field = request.resolution.get("field")
        corrected_value = request.resolution.get("corrected_value")
        if not isinstance(field, str):
            raise AppError("CORRECTION_FIELD_MISSING", "Correction field is required.", 400)

        record = self.db.get(CanonicalRecord, escalation.record_id)
        if record is None:
            raise AppError("CANONICAL_RECORD_NOT_FOUND", "Canonical record was not found.", 404)

        data = json.loads(record.data_json)
        cleaned, clean_issues = clean_value(field, corrected_value)
        data[field] = cleaned

        validation_status, validation_issues = ValidationService().validate(data)
        record.data_json = _dump_json(data)
        record.validation_status = validation_status
        record.issues_json = _dump_json(clean_issues + validation_issues)

    def _apply_approval(self, escalation: Escalation) -> None:
        if escalation.record_id is None:
            return

        record = self.db.get(CanonicalRecord, escalation.record_id)
        if record is None:
            raise AppError("CANONICAL_RECORD_NOT_FOUND", "Canonical record was not found.", 404)

        record.validation_status = ValidationStatus.VALID
        record.issues_json = "[]"

    def _apply_mapping_resolution(
        self,
        escalation: Escalation,
        request: ResolveEscalationRequest,
        user: User,
    ) -> None:
        context = json.loads(escalation.payload_json)
        mapping_id = context.get("mapping_id")
        if not isinstance(mapping_id, str):
            raise AppError("MAPPING_REVIEW_NOT_APPLICABLE", "This review item has no mapping.", 400)

        mapping = self.db.get(Mapping, mapping_id)
        if mapping is None:
            raise AppError("MAPPING_NOT_FOUND", "Mapping was not found.", 404)

        if request.action == "APPROVE":
            if mapping.target_field is None:
                raise AppError(
                    "MAPPING_TARGET_MISSING",
                    "Choose a target field before approving this mapping.",
                    400,
                )
            mapping.decision = MappingDecision.MANUALLY_APPROVED
        elif request.action == "CORRECT":
            target_field = request.resolution.get("target_field") or request.resolution.get("corrected_value")
            if not isinstance(target_field, str):
                raise AppError("MAPPING_TARGET_MISSING", "Target field is required.", 400)
            if target_field not in TARGET_FIELD_TYPES:
                raise AppError("INVALID_TARGET_FIELD", "Target field is not in the target schema.", 400)
            mapping.target_field = target_field
            mapping.decision = MappingDecision.MANUALLY_CORRECTED
        elif request.action == "REJECT":
            mapping.target_field = None
            mapping.decision = MappingDecision.REJECTED
        else:
            raise AppError("UNSUPPORTED_MAPPING_ACTION", "Mapping review action is not supported.", 400)

        mapping.reviewed_by = user.id

    def _existing_issue_keys(self, migration_id: str) -> set[str]:
        escalations = self.db.scalars(
            select(Escalation).where(Escalation.migration_id == migration_id)
        ).all()
        keys: set[str] = set()
        for escalation in escalations:
            if escalation.record_id is None:
                continue
            try:
                context = json.loads(escalation.payload_json)
            except json.JSONDecodeError:
                continue
            issue_key = context.get("issue_key")
            if isinstance(issue_key, str):
                keys.add(issue_key)
            else:
                keys.add(_issue_key(escalation.record_id, context))
        return keys

    def _existing_mapping_review_ids(self, migration_id: str) -> set[str]:
        escalations = self.db.scalars(
            select(Escalation).where(Escalation.migration_id == migration_id)
        ).all()
        mapping_ids: set[str] = set()
        for escalation in escalations:
            try:
                context = json.loads(escalation.payload_json)
            except json.JSONDecodeError:
                continue
            mapping_id = context.get("mapping_id")
            if isinstance(mapping_id, str):
                mapping_ids.add(mapping_id)
        return mapping_ids


def _dump_json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


def _review_context(
    record: CanonicalRecord,
    data: dict[str, Any],
    provenance: dict[str, Any],
    issue: dict[str, Any],
) -> dict[str, Any]:
    issue_type = str(issue.get("type", "UNKNOWN"))
    field = str(issue.get("field") or _field_from_validation_reason(issue) or "")
    current_value = issue.get("value") or issue.get("incoming")
    if current_value is None and field:
        current_value = data.get(field)

    field_source = provenance.get(field) if field else None
    evidence = _evidence_for_issue(issue, field, current_value, field_source)
    summary, reason, recommended_action = _operator_copy(issue_type, field)

    return {
        **issue,
        "issue_key": _issue_key(record.id, issue),
        "employee_id": record.employee_id,
        "record_data": data,
        "summary": summary,
        "reason": reason,
        "recommended_action_text": recommended_action,
        "editable_field": field or None,
        "current_value": str(current_value) if current_value is not None else "",
        "evidence": evidence,
        "source": field_source,
    }


def _mapping_review_context(mapping: Mapping) -> dict[str, Any]:
    alternatives = json.loads(mapping.alternatives_json or "[]")
    confidence_label = _confidence_label(mapping.final_score)
    evidence = [
        {"label": "Source column", "value": mapping.source_column},
        {"label": "Recommended target", "value": mapping.target_field or "No safe target found"},
        {"label": "Confidence", "value": confidence_label},
    ]
    if mapping.reasoning:
        evidence.append({"label": "Why", "value": mapping.reasoning})

    return {
        "mapping_id": mapping.id,
        "type": "MAPPING_AMBIGUITY"
        if mapping.decision == MappingDecision.NEEDS_REVIEW
        else "MAPPING_BLOCKED",
        "source_column": mapping.source_column,
        "target_field": mapping.target_field,
        "current_value": mapping.target_field or "",
        "editable_field": "target_field",
        "confidence": mapping.final_score,
        "confidence_label": confidence_label,
        "alternatives": alternatives,
        "summary": f"Review mapping for {mapping.source_column}",
        "reason": mapping.reasoning
        or "The system could not safely choose a target field for this source column.",
        "recommended_action_text": "Approve the recommendation, choose a different target field, or reject this source column.",
        "evidence": evidence,
    }


def _confidence_label(score: float) -> str:
    if score >= 0.85:
        return "High confidence"
    if score >= 0.60:
        return "Medium confidence"
    return "Low confidence"


def _operator_copy(issue_type: str, field: str) -> tuple[str, str, str]:
    friendly_field = field.replace("_", " ") if field else "record"
    if issue_type == "NUMERIC_OUTLIER":
        return (
            f"{friendly_field.title()} looks unusual",
            "This value is far away from the other values in the uploaded files, so it needs a human check before migration.",
            "If the value is correct, approve it. If it is a mistake, enter the corrected value and save.",
        )
    if issue_type == "SOURCE_VALUE_CONFLICT":
        return (
            f"{friendly_field.title()} has conflicting source values",
            "Two uploaded files gave different values and the system could not safely decide which one to use.",
            "Choose or enter the correct value before continuing.",
        )
    if issue_type in {"AMBIGUOUS_DATE_FORMAT", "INVALID_DATE_FORMAT"}:
        return (
            f"{friendly_field.title()} date is unclear",
            "The date format could not be read safely. This commonly happens with dates like 04/05/2021.",
            "Enter the date in YYYY-MM-DD format.",
        )
    if issue_type == "VALIDATION_FAILED":
        if field:
            return (
                f"{friendly_field.title()} is missing or invalid",
                f"The {friendly_field} value is required or not in the expected format.",
                f"Ask HR for the correct {friendly_field}, or enter it if you already know it.",
            )
        return (
            "Record failed validation",
            "A required value is missing or one of the employee fields does not meet the target rules.",
            "Review the current value and enter the correct value if needed.",
        )
    return (
        f"{friendly_field.title()} needs review",
        "The system found something that should be checked before this employee is migrated.",
        "Approve the value if it is correct, or enter a corrected value.",
    )


def _evidence_for_issue(
    issue: dict[str, Any],
    field: str,
    current_value: Any,
    field_source: Any,
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    if field:
        evidence.append({"label": "Field", "value": field.replace("_", " ")})
    if current_value is not None:
        evidence.append({"label": "Current value", "value": str(current_value)})
    if "existing" in issue:
        evidence.append({"label": "Existing value", "value": str(issue["existing"])})
    if "incoming" in issue:
        evidence.append({"label": "Incoming value", "value": str(issue["incoming"])})
    if isinstance(issue.get("existing_source"), dict):
        existing_source = issue["existing_source"]
        evidence.append(
            {
                "label": "Existing source",
                "value": _source_label(existing_source),
            }
        )
    if isinstance(issue.get("incoming_source"), dict):
        incoming_source = issue["incoming_source"]
        evidence.append(
            {
                "label": "Incoming source",
                "value": _source_label(incoming_source),
            }
        )
    if isinstance(field_source, dict):
        evidence.extend(
            [
                {"label": "Source file", "value": str(field_source.get("source_file", "unknown"))},
                {"label": "Source column", "value": str(field_source.get("source_column", "unknown"))},
                {"label": "Source row", "value": str(field_source.get("source_row", "unknown"))},
                {"label": "Original value", "value": str(field_source.get("original_value", "unknown"))},
            ]
        )
    if "reason" in issue:
        evidence.append({"label": "Issue", "value": _friendly_validation_message(issue, field)})
    return evidence


def _source_label(source: dict[str, Any]) -> str:
    return (
        f"{source.get('source_file', 'unknown')} / "
        f"{source.get('source_column', 'unknown')} / "
        f"row {source.get('source_row', 'unknown')}"
    )


def _field_from_validation_reason(issue: dict[str, Any]) -> str | None:
    reason = str(issue.get("reason") or "")
    for field in ("joining_date", "annual_salary", "currency", "pay_frequency", "manager_id"):
        if field in reason:
            return field
    return None


def _friendly_validation_message(issue: dict[str, Any], field: str) -> str:
    issue_type = str(issue.get("type") or "")
    reason = str(issue.get("reason") or "")
    friendly_field = field.replace("_", " ") if field else "required field"
    if issue_type == "VALIDATION_FAILED" and "Field required" in reason:
        return f"{friendly_field.title()} is missing."
    if issue_type == "VALIDATION_FAILED" and "valid email" in reason.lower():
        return "Email address is not valid."
    if issue_type == "VALIDATION_FAILED":
        return f"{friendly_field.title()} does not meet the target format rules."
    return reason


def _is_mapping_escalation(escalation: Escalation) -> bool:
    return escalation.issue_type in {"MAPPING_AMBIGUITY", "MAPPING_BLOCKED"}


def _issue_key(record_id: str, issue: dict[str, Any]) -> str:
    return "|".join(
        [
            record_id,
            str(issue.get("type", "UNKNOWN")),
            str(issue.get("field", "")),
            str(issue.get("value", "")),
            str(issue.get("existing", "")),
            str(issue.get("incoming", "")),
            str(issue.get("reason", "")),
        ]
    )
