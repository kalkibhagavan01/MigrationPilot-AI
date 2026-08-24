import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.enums import MappingDecision, ValidationStatus
from app.db.session import SessionLocal
from app.main import create_app
from app.models.canonical_record import CanonicalRecord
from app.models.column_profile import ColumnProfile
from app.models.mapping import Mapping
from app.models.migration import Migration
from app.models.source_file import SourceFile
from app.models.user import User
from app.services.canonicalization import CanonicalizationService


def test_validation_repair_makes_safe_enum_and_email_record_valid(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'repair-valid.db'}")):
        migration_id = _seed_repairable_source_file(
            (
                "employee_id,full_name,email,joining_date,employment_type\n"
                "E001,Asha Rao, ASHA@EXAMPLE.COM ,2022-04-01,full time\n"
            )
        )
        with SessionLocal() as db:
            records = CanonicalizationService(db).canonicalize(migration_id)
            db.commit()

    assert len(records) == 1

    with SessionLocal() as db:
        record = db.scalar(select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id))

    assert record is not None
    assert record.validation_status == ValidationStatus.VALID
    assert record.validation_attempts == 1
    assert json.loads(record.data_json)["email"] == "asha@example.com"
    assert json.loads(record.data_json)["employment_type"] == "PERMANENT"


def test_validation_repair_attempt_is_bounded_when_record_still_invalid(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'repair-invalid.db'}")):
        migration_id = _seed_repairable_source_file(
            (
                "employee_id,full_name,email,joining_date,annual_salary\n"
                "E001,Asha Rao,asha@example.com,2022-04-01,1000000\n"
            )
        )
        with SessionLocal() as db:
            records = CanonicalizationService(db).canonicalize(migration_id)
            db.commit()

    assert len(records) == 1

    with SessionLocal() as db:
        record = db.scalar(select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id))

    assert record is not None
    assert record.validation_status == ValidationStatus.INVALID
    assert record.validation_attempts == 2
    assert any(issue["type"] == "VALIDATION_FAILED" for issue in json.loads(record.issues_json))


def _seed_repairable_source_file(csv_content: str) -> str:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "consultant"))
        assert user is not None
        migration = Migration(
            status="PROFILING",
            created_by=user.id,
            target_schema_version="employee-v1",
        )
        db.add(migration)
        db.flush()
        source = SourceFile(
            migration_id=migration.id,
            original_name="employees_master.csv",
            stored_path=f"/tmp/{migration.id}.csv",
            file_type="csv",
            size_bytes=len(csv_content),
            checksum_sha256="repair",
            row_count=1,
        )
        db.add(source)
        db.flush()
        from pathlib import Path

        Path(source.stored_path).write_text(csv_content, encoding="utf-8")
        for column in csv_content.splitlines()[0].split(","):
            db.add(
                ColumnProfile(
                    source_file_id=source.id,
                    sheet_name=None,
                    column_name=column,
                    normalized_name=column,
                    inferred_type="string",
                    null_ratio=0,
                    unique_ratio=1,
                    sample_values_json="[]",
                    profile_json="{}",
                )
            )
            db.add(
                Mapping(
                    migration_id=migration.id,
                    source_file_id=source.id,
                    source_column=column,
                    target_field=column,
                    semantic_score=1,
                    name_score=1,
                    type_score=1,
                    value_score=1,
                    final_score=1,
                    decision=MappingDecision.AUTO_APPROVED,
                    decision_source="TEST",
                    reasoning="test",
                    alternatives_json="[]",
                )
            )
        db.commit()
        return migration.id
