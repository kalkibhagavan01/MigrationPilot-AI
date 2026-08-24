from typing import TypedDict


class MigrationGraphState(TypedDict, total=False):
    run_id: str
    migration_id: str
    thread_id: str
    status: str
    current_stage: str
    current_node: str
    source_file_ids: list[str]
    source_rows: list[str]
    canonical_record_ids: list[str]
    profile_ids: list[str]
    inferred_mapping_ids: list[str]
    mapping_decisions: dict[str, str]
    cleaned_record_ids: list[str]
    validated_record_ids: list[str]
    pending_escalation_ids: list[str]
    human_decision_ids: list[str]
    target_result_ids: list[str]
    mapping_autonomy_action: str
    record_autonomy_action: str
    node_visit_counts: dict[str, int]
    total_transitions: int
    error_code: str | None
    error_message: str | None
