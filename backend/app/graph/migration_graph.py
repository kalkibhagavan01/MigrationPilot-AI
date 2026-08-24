import json
from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.constants import MAX_GRAPH_TRANSITIONS, MAX_NODE_VISITS
from app.core.enums import (
    AuditActorType,
    EscalationStatus,
    MappingDecision,
    MigrationStatus,
    ValidationStatus,
)
from app.core.errors import AppError
from app.graph.state import MigrationGraphState
from app.models.canonical_record import CanonicalRecord
from app.models.escalation import Escalation
from app.models.mapping import Mapping
from app.models.migration import Migration
from app.models.user import User
from app.schemas.audit import AuditEventCreate
from app.services.audit import AuditService
from app.services.canonicalization import CanonicalizationService
from app.services.escalation import EscalationService
from app.services.llm import NvidiaLLMProvider
from app.services.mapping import MappingService
from app.services.target import TargetIntegrationService


AutonomyRoute = str


def build_migration_graph(
    db: Session,
    settings: Settings,
    user: User,
    checkpointer=None,
):
    graph = StateGraph(MigrationGraphState)
    graph.add_node("generate_mappings_node", _generate_mappings_node(db, settings, user))
    graph.add_node("evaluate_mapping_autonomy_node", _evaluate_mapping_autonomy_node(db))
    graph.add_node("mapping_review_gate_node", _mapping_review_gate_node(db))
    graph.add_node("canonicalize_records_node", _canonicalize_records_node(db))
    graph.add_node("evaluate_record_autonomy_node", _evaluate_record_autonomy_node(db))
    graph.add_node("data_review_gate_node", _data_review_gate_node(db))
    graph.add_node("push_records_node", _push_records_node(db))
    graph.add_node("finalize_node", _finalize_node(db))

    graph.add_edge(START, "generate_mappings_node")
    graph.add_edge("generate_mappings_node", "evaluate_mapping_autonomy_node")
    graph.add_conditional_edges(
        "evaluate_mapping_autonomy_node",
        _mapping_route,
        {
            "AUTO": "canonicalize_records_node",
            "HITL": "mapping_review_gate_node",
            "STOP": "finalize_node",
        },
    )
    graph.add_edge("mapping_review_gate_node", "canonicalize_records_node")
    graph.add_edge("canonicalize_records_node", "evaluate_record_autonomy_node")
    graph.add_conditional_edges(
        "evaluate_record_autonomy_node",
        _record_route,
        {
            "AUTO": "push_records_node",
            "HITL": "data_review_gate_node",
            "STOP": "finalize_node",
        },
    )
    graph.add_edge("data_review_gate_node", "push_records_node")
    graph.add_edge("push_records_node", "finalize_node")
    graph.add_edge("finalize_node", END)
    return graph.compile(checkpointer=checkpointer)


def _generate_mappings_node(
    db: Session,
    settings: Settings,
    user: User,
) -> Callable[[MigrationGraphState], MigrationGraphState]:
    def node(state: MigrationGraphState) -> MigrationGraphState:
        state = _mark_node(state, "generate_mappings_node", MigrationStatus.MAPPING)
        migration_id = _migration_id(state)
        before_count = _mapping_count(db, migration_id)
        llm_provider = NvidiaLLMProvider(settings) if settings.nvidia_api_key.strip() else None
        mappings = MappingService(db, llm_provider=llm_provider).generate_for_migration(migration_id)

        if before_count == 0:
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
                            "decision_source": mapping.decision_source,
                            "reason": mapping.reasoning,
                        },
                    )
                )

        _set_migration_node(db, migration_id, MigrationStatus.MAPPING, "generate_mappings_node")
        return {**state, "inferred_mapping_ids": [mapping.id for mapping in mappings]}

    return node


def _evaluate_mapping_autonomy_node(
    db: Session,
) -> Callable[[MigrationGraphState], MigrationGraphState]:
    def node(state: MigrationGraphState) -> MigrationGraphState:
        state = _mark_node(state, "evaluate_mapping_autonomy_node", MigrationStatus.MAPPING)
        migration_id = _migration_id(state)
        mappings = list(
            db.scalars(
                select(Mapping)
                .where(Mapping.migration_id == migration_id)
                .order_by(Mapping.source_column)
            )
        )
        decisions = {mapping.source_column: str(mapping.decision) for mapping in mappings}

        if any(mapping.decision == MappingDecision.BLOCKED for mapping in mappings):
            _set_migration_node(
                db,
                migration_id,
                MigrationStatus.BLOCKED,
                "evaluate_mapping_autonomy_node",
            )
            return {
                **state,
                "mapping_decisions": decisions,
                "mapping_autonomy_action": "STOP",
                "error_code": "MAPPING_BLOCKED",
                "error_message": "One or more source columns could not be mapped safely.",
            }

        if any(mapping.decision == MappingDecision.NEEDS_REVIEW for mapping in mappings):
            return {
                **state,
                "mapping_decisions": decisions,
                "mapping_autonomy_action": "HITL",
            }

        return {**state, "mapping_decisions": decisions, "mapping_autonomy_action": "AUTO"}

    return node


def _mapping_review_gate_node(db: Session) -> Callable[[MigrationGraphState], MigrationGraphState]:
    def node(state: MigrationGraphState) -> MigrationGraphState:
        state = _mark_node(state, "mapping_review_gate_node", MigrationStatus.WAITING_FOR_REVIEW)
        migration_id = _migration_id(state)
        EscalationService(db).build_mapping_reviews(migration_id)
        open_ids = _open_review_ids(db, migration_id)
        if not open_ids:
            return {**state, "pending_escalation_ids": []}

        _set_migration_node(db, migration_id, MigrationStatus.WAITING_FOR_REVIEW, "mapping_review_gate_node")
        decision = interrupt(
            {
                "type": "MAPPING_REVIEW_REQUIRED",
                "title": "Mapping review is required before records are created",
                "migration_id": migration_id,
                "pending_escalation_ids": open_ids,
            }
        )
        human_decisions = list(state.get("human_decision_ids", []))
        if isinstance(decision, dict) and decision.get("decision_id"):
            human_decisions.append(str(decision["decision_id"]))
        return {**state, "pending_escalation_ids": [], "human_decision_ids": human_decisions}

    return node


def _canonicalize_records_node(db: Session) -> Callable[[MigrationGraphState], MigrationGraphState]:
    def node(state: MigrationGraphState) -> MigrationGraphState:
        state = _mark_node(state, "canonicalize_records_node", MigrationStatus.VALIDATING)
        migration_id = _migration_id(state)
        if _open_review_ids(db, migration_id):
            _set_migration_node(
                db,
                migration_id,
                MigrationStatus.WAITING_FOR_REVIEW,
                "canonicalize_records_node",
            )
            return {
                **state,
                "record_autonomy_action": "STOP",
                "error_code": "OPEN_REVIEWS_BLOCK_CANONICALIZATION",
                "error_message": "Resolve mapping reviews before canonical records are created.",
            }

        records = list(
            db.scalars(select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id))
        )
        if not records:
            records = CanonicalizationService(db).canonicalize(migration_id)

        valid_records = sum(1 for record in records if record.validation_status == ValidationStatus.VALID)
        review_records = sum(
            1 for record in records if record.validation_status == ValidationStatus.NEEDS_REVIEW
        )
        invalid_records = sum(1 for record in records if record.validation_status == ValidationStatus.INVALID)
        migration = db.get(Migration, migration_id)
        if migration:
            migration.status = MigrationStatus.VALIDATING
            migration.current_node = "canonicalize_records_node"
            migration.valid_records = valid_records
            migration.failed_records = invalid_records + review_records
        db.flush()
        return {**state, "canonical_record_ids": [record.id for record in records]}

    return node


def _evaluate_record_autonomy_node(
    db: Session,
) -> Callable[[MigrationGraphState], MigrationGraphState]:
    def node(state: MigrationGraphState) -> MigrationGraphState:
        state = _mark_node(state, "evaluate_record_autonomy_node", MigrationStatus.VALIDATING)
        migration_id = _migration_id(state)
        records = list(
            db.scalars(select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id))
        )
        if not records:
            _set_migration_node(db, migration_id, MigrationStatus.BLOCKED, "evaluate_record_autonomy_node")
            return {
                **state,
                "record_autonomy_action": "STOP",
                "error_code": "NO_CANONICAL_RECORDS",
                "error_message": "No canonical records were produced.",
            }

        for record in records:
            issues = json.loads(record.issues_json or "[]")
            if record.validation_status in {ValidationStatus.INVALID, ValidationStatus.NEEDS_REVIEW}:
                return {**state, "record_autonomy_action": "HITL"}
            if record.validation_attempts >= 2 and issues:
                return {**state, "record_autonomy_action": "HITL"}
            if any(_issue_requires_review(issue) for issue in issues):
                return {**state, "record_autonomy_action": "HITL"}

        return {**state, "record_autonomy_action": "AUTO"}

    return node


def _data_review_gate_node(db: Session) -> Callable[[MigrationGraphState], MigrationGraphState]:
    def node(state: MigrationGraphState) -> MigrationGraphState:
        state = _mark_node(state, "data_review_gate_node", MigrationStatus.WAITING_FOR_REVIEW)
        migration_id = _migration_id(state)
        EscalationService(db).build_for_migration(migration_id)
        open_ids = _open_review_ids(db, migration_id)
        if not open_ids:
            return {**state, "pending_escalation_ids": []}

        _set_migration_node(db, migration_id, MigrationStatus.WAITING_FOR_REVIEW, "data_review_gate_node")
        decision = interrupt(
            {
                "type": "DATA_REVIEW_REQUIRED",
                "title": "Record review is required before target push",
                "migration_id": migration_id,
                "pending_escalation_ids": open_ids,
            }
        )
        human_decisions = list(state.get("human_decision_ids", []))
        if isinstance(decision, dict) and decision.get("decision_id"):
            human_decisions.append(str(decision["decision_id"]))
        return {**state, "pending_escalation_ids": [], "human_decision_ids": human_decisions}

    return node


def _push_records_node(db: Session) -> Callable[[MigrationGraphState], MigrationGraphState]:
    def node(state: MigrationGraphState) -> MigrationGraphState:
        state = _mark_node(state, "push_records_node", MigrationStatus.PUSHING)
        migration_id = _migration_id(state)
        if _open_review_ids(db, migration_id):
            _set_migration_node(db, migration_id, MigrationStatus.WAITING_FOR_REVIEW, "push_records_node")
            return {
                **state,
                "error_code": "OPEN_REVIEWS_BLOCK_PUSH",
                "error_message": "Resolve open reviews before target push.",
            }

        valid_count = int(
            db.scalar(
                select(func.count(CanonicalRecord.id)).where(
                    CanonicalRecord.migration_id == migration_id,
                    CanonicalRecord.validation_status == ValidationStatus.VALID,
                )
            )
            or 0
        )
        if valid_count == 0:
            _set_migration_node(db, migration_id, MigrationStatus.BLOCKED, "push_records_node")
            return {
                **state,
                "status": str(MigrationStatus.BLOCKED),
                "error_code": "NO_VALID_RECORDS_TO_PUSH",
                "error_message": "No records meet the target schema after review decisions.",
            }

        migration = db.get(Migration, migration_id)
        if migration and migration.status in {
            MigrationStatus.COMPLETED,
            MigrationStatus.PARTIALLY_COMPLETED,
            MigrationStatus.ROLLED_BACK,
            MigrationStatus.CANCELLED,
        }:
            return state

        results = TargetIntegrationService(db).push_migration(migration_id)
        return {**state, "target_result_ids": [result.record_id for result in results]}

    return node


def _finalize_node(db: Session) -> Callable[[MigrationGraphState], MigrationGraphState]:
    def node(state: MigrationGraphState) -> MigrationGraphState:
        state = _mark_node(state, "finalize_node", None)
        migration_id = _migration_id(state)
        migration = db.get(Migration, migration_id)
        if not migration:
            return state
        db.flush()
        return {
            **state,
            "status": str(migration.status),
            "current_node": migration.current_node or state.get("current_node"),
        }

    return node


def _mark_node(
    state: MigrationGraphState,
    node_name: str,
    status: MigrationStatus | None,
) -> MigrationGraphState:
    counts = dict(state.get("node_visit_counts", {}))
    counts[node_name] = counts.get(node_name, 0) + 1
    transitions = state.get("total_transitions", 0) + 1
    migration_id = _migration_id(state)
    next_state: MigrationGraphState = {
        **state,
        "run_id": state.get("run_id") or migration_id,
        "thread_id": state.get("thread_id") or migration_id,
        "current_stage": node_name,
        "current_node": node_name,
        "node_visit_counts": counts,
        "total_transitions": transitions,
    }
    if status is not None:
        next_state["status"] = str(status)
    if counts[node_name] > MAX_NODE_VISITS or transitions > MAX_GRAPH_TRANSITIONS:
        raise AppError(
            "GRAPH_LOOP_GUARD_TRIGGERED",
            "Migration graph loop guard triggered.",
            500,
        )
    return next_state


def _mapping_route(state: MigrationGraphState) -> AutonomyRoute:
    return state.get("mapping_autonomy_action", "STOP")


def _record_route(state: MigrationGraphState) -> AutonomyRoute:
    return state.get("record_autonomy_action", "STOP")


def _migration_id(state: MigrationGraphState) -> str:
    migration_id = state.get("migration_id") or state.get("thread_id") or state.get("run_id")
    if not migration_id:
        raise AppError("MIGRATION_ID_MISSING", "Migration graph state is missing migration id.", 500)
    return migration_id


def _set_migration_node(
    db: Session,
    migration_id: str,
    status: MigrationStatus,
    current_node: str,
) -> None:
    migration = db.get(Migration, migration_id)
    if migration:
        migration.status = status
        migration.current_node = current_node
    db.flush()


def _open_review_ids(db: Session, migration_id: str) -> list[str]:
    return list(
        db.scalars(
            select(Escalation.id)
            .where(Escalation.migration_id == migration_id, Escalation.status == EscalationStatus.OPEN)
            .order_by(Escalation.created_at)
        )
    )


def _mapping_count(db: Session, migration_id: str) -> int:
    return int(
        db.scalar(select(func.count(Mapping.id)).where(Mapping.migration_id == migration_id)) or 0
    )


def _issue_requires_review(issue: dict[str, object]) -> bool:
    issue_type = str(issue.get("type", ""))
    return issue_type in {
        "SOURCE_VALUE_CONFLICT",
        "NUMERIC_OUTLIER",
        "MISSING_REQUIRED_FIELD",
        "INVALID_FIELD",
        "VALIDATION_ERROR",
    } or bool(issue)
