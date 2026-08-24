from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.core.errors import AppError
from app.graph.migration_graph import build_migration_graph
from app.graph.state import MigrationGraphState
from app.models.migration import Migration
from app.models.user import User


class MigrationGraphRunner:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def start(self, migration_id: str, user: User) -> MigrationGraphState:
        migration = self.db.get(Migration, migration_id)
        if migration is None:
            raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)

        state: MigrationGraphState = {
            "run_id": migration_id,
            "migration_id": migration_id,
            "thread_id": migration_id,
            "status": str(migration.status),
            "current_node": migration.current_node,
        }
        return self._invoke(state, user)

    def resume(
        self,
        migration_id: str,
        user: User,
        resume_payload: dict[str, object],
    ) -> MigrationGraphState:
        migration = self.db.get(Migration, migration_id)
        if migration is None:
            raise AppError("MIGRATION_NOT_FOUND", "Migration was not found.", 404)
        return self._invoke(Command(resume=resume_payload), user, migration_id)

    def _invoke(
        self,
        payload: MigrationGraphState | Command,
        user: User,
        migration_id: str | None = None,
    ) -> MigrationGraphState:
        checkpoint_path = self._checkpoint_path()
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        thread_id = (
            migration_id
            or payload.get("thread_id")  # type: ignore[union-attr]
            or payload.get("migration_id")  # type: ignore[union-attr]
        )
        if not thread_id:
            raise AppError("GRAPH_THREAD_ID_MISSING", "Migration graph thread id is missing.", 500)

        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            graph = build_migration_graph(self.db, self.settings, user, checkpointer=saver)
            result = graph.invoke(payload, {"configurable": {"thread_id": str(thread_id)}})
        return result

    def _checkpoint_path(self) -> Path:
        configured = Path(self.settings.langgraph_checkpoint_path)
        if configured.is_absolute():
            return configured
        return PROJECT_ROOT / configured
