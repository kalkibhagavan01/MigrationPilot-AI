from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.constants import MAX_GRAPH_TRANSITIONS, MAX_NODE_VISITS
from app.graph.state import MigrationGraphState


def build_phase2_graph(checkpointer=None):
    graph = StateGraph(MigrationGraphState)
    graph.add_node("validate_input", _mark_node("validate_input"))
    graph.add_node("ingest_files", _mark_node("ingest_files"))
    graph.add_node("profile_files", _mark_node("profile_files"))
    graph.add_node("generate_mapping_candidates", _mark_node("generate_mapping_candidates"))
    graph.add_node("validate_records", _mark_node("validate_records"))
    graph.add_node("create_record_escalations", _review_or_mark_node("create_record_escalations"))

    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "ingest_files")
    graph.add_edge("ingest_files", "profile_files")
    graph.add_edge("profile_files", "generate_mapping_candidates")
    graph.add_edge("generate_mapping_candidates", "validate_records")
    graph.add_edge("validate_records", "create_record_escalations")
    graph.add_edge("create_record_escalations", END)
    return graph.compile(checkpointer=checkpointer)


def _mark_node(node_name: str):
    def node(state: MigrationGraphState) -> MigrationGraphState:
        counts = dict(state.get("node_visit_counts", {}))
        counts[node_name] = counts.get(node_name, 0) + 1
        transitions = state.get("total_transitions", 0) + 1

        if counts[node_name] > MAX_NODE_VISITS or transitions > MAX_GRAPH_TRANSITIONS:
            return {
                **state,
                "run_id": _run_id(state),
                "thread_id": _thread_id(state),
                "status": "BLOCKED",
                "current_stage": node_name,
                "current_node": node_name,
                "node_visit_counts": counts,
                "total_transitions": transitions,
                "error_code": "GRAPH_LOOP_GUARD_TRIGGERED",
                "error_message": "Graph loop guard triggered.",
            }

        return {
            **state,
            "run_id": _run_id(state),
            "thread_id": _thread_id(state),
            "status": _status_for_node(node_name, state),
            "current_stage": node_name,
            "current_node": node_name,
            "node_visit_counts": counts,
            "total_transitions": transitions,
        }

    return node


def _review_or_mark_node(node_name: str):
    mark_node = _mark_node(node_name)

    def node(state: MigrationGraphState) -> MigrationGraphState:
        next_state = mark_node(state)
        pending = list(next_state.get("pending_escalation_ids", []))
        if not pending:
            return next_state

        decision = interrupt(
            {
                "type": "HUMAN_REVIEW_REQUIRED",
                "title": "Review is required before migration can continue",
                "run_id": _run_id(next_state),
                "pending_escalation_ids": pending,
            }
        )
        human_decisions = list(next_state.get("human_decision_ids", []))
        if isinstance(decision, dict) and decision.get("decision_id"):
            human_decisions.append(str(decision["decision_id"]))
        return {
            **next_state,
            "status": "VALIDATING",
            "pending_escalation_ids": [],
            "human_decision_ids": human_decisions,
        }

    return node


def _status_for_node(node_name: str, state: MigrationGraphState) -> str:
    if node_name == "profile_files":
        return "PROFILING"
    if node_name == "generate_mapping_candidates":
        return "MAPPING"
    if node_name == "validate_records":
        return "VALIDATING"
    if node_name == "create_record_escalations":
        return "WAITING_FOR_REVIEW"
    return state.get("status", "CREATED")


def _run_id(state: MigrationGraphState) -> str:
    return state.get("run_id") or state.get("migration_id") or state.get("thread_id") or ""


def _thread_id(state: MigrationGraphState) -> str:
    return state.get("thread_id") or _run_id(state)
