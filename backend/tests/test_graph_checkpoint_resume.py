from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.graph.builder import build_phase2_graph


def test_graph_interrupts_and_resumes_from_sqlite_checkpoint(tmp_path) -> None:
    checkpoint_path = tmp_path / "graph-checkpoints.sqlite"

    with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        graph = build_phase2_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": "migration-1"}}

        interrupted = graph.invoke(
            {
                "run_id": "migration-1",
                "migration_id": "migration-1",
                "status": "CREATED",
                "pending_escalation_ids": ["esc-1"],
            },
            config,
        )

    assert checkpoint_path.exists()
    assert "__interrupt__" in interrupted
    assert interrupted["__interrupt__"][0].value["pending_escalation_ids"] == ["esc-1"]

    with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        graph = build_phase2_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": "migration-1"}}
        resumed = graph.invoke(Command(resume={"decision_id": "decision-1"}), config)

    assert resumed["thread_id"] == "migration-1"
    assert resumed["pending_escalation_ids"] == []
    assert resumed["human_decision_ids"] == ["decision-1"]
    assert resumed["current_node"] == "create_record_escalations"
