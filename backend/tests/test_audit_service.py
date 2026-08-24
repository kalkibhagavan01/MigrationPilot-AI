from decimal import Decimal

from sqlalchemy import select

from app.core.enums import AuditActorType
from app.db.bootstrap import initialize_database
from app.db.session import SessionLocal, configure_database
from app.models.audit import AuditEvent
from app.schemas.audit import AuditEventCreate
from app.services.audit import AuditService


def test_audit_service_appends_and_lists_events(tmp_path) -> None:
    engine = configure_database(f"sqlite:///{tmp_path / 'audit.db'}")
    initialize_database(engine)

    with SessionLocal() as db:
        service = AuditService(db)
        created = service.append(
            AuditEventCreate(
                migration_id="migration-1",
                actor_type=AuditActorType.SYSTEM,
                event_type="FILE_INGESTED",
                entity_type="source_file",
                entity_id="file-1",
                metadata={"file_name": "employees_master.csv"},
            )
        )
        events = service.list_for_migration("migration-1")

    assert created.id
    assert len(events) == 1
    assert events[0].event_type == "FILE_INGESTED"
    assert events[0].metadata_json == '{"file_name":"employees_master.csv"}'


def test_audit_rows_are_persisted_without_public_mutation_api(tmp_path) -> None:
    engine = configure_database(f"sqlite:///{tmp_path / 'audit_persisted.db'}")
    initialize_database(engine)

    with SessionLocal() as db:
        service = AuditService(db)
        service.append(
            AuditEventCreate(
                migration_id="migration-2",
                actor_type=AuditActorType.AGENT,
                event_type="MAPPING_AUTO_APPROVED",
                entity_type="mapping",
            )
        )
        persisted = db.scalar(select(AuditEvent).where(AuditEvent.migration_id == "migration-2"))

    assert persisted is not None
    assert persisted.event_type == "MAPPING_AUTO_APPROVED"


def test_audit_service_serializes_decimal_metadata(tmp_path) -> None:
    engine = configure_database(f"sqlite:///{tmp_path / 'audit_decimal.db'}")
    initialize_database(engine)

    with SessionLocal() as db:
        service = AuditService(db)
        event = service.append(
            AuditEventCreate(
                migration_id="migration-3",
                actor_type=AuditActorType.SYSTEM,
                event_type="SOURCE_VALUE_CONFLICT",
                entity_type="canonical_record",
                metadata={"incoming": Decimal("2100000")},
            )
        )

    assert event.metadata_json == '{"incoming":"2100000"}'
