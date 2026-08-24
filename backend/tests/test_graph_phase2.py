from app.graph.builder import build_phase2_graph


def test_phase_graph_runs_through_mapping_node() -> None:
    graph = build_phase2_graph()
    result = graph.invoke({"run_id": "m1", "migration_id": "m1", "status": "CREATED"})

    assert result["run_id"] == "m1"
    assert result["thread_id"] == "m1"
    assert result["current_node"] == "create_record_escalations"
    assert result["current_stage"] == "create_record_escalations"
    assert result["status"] == "WAITING_FOR_REVIEW"
    assert result["total_transitions"] == 6
    assert result["node_visit_counts"] == {
        "validate_input": 1,
        "ingest_files": 1,
        "profile_files": 1,
        "generate_mapping_candidates": 1,
        "validate_records": 1,
        "create_record_escalations": 1,
    }
