import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.enums import MigrationStatus, PushStatus, ValidationStatus
from app.db.session import SessionLocal
from app.main import create_app
from app.models.canonical_record import CanonicalRecord
from app.models.migration import Migration
from app.models.mock_target import MockTargetRecord
from app.models.push_attempt import PushAttempt
from app.models.user import User
from app.schemas.audit import AuditEventCreate
from app.services.audit import AuditService


def test_mock_target_idempotency_returns_same_record(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'mock.db'}")) as client:
        payload = {
            "employee_id": "E001",
            "full_name": "Asha Rao",
            "email": "asha@example.com",
            "joining_date": "2022-04-01",
        }
        first = client.post(
            "/api/v1/mock-target/v1/employees",
            headers={"Idempotency-Key": "migration:E001"},
            json=payload,
        )
        second = client.post(
            "/api/v1/mock-target/v1/employees",
            headers={"Idempotency-Key": "migration:E001"},
            json=payload,
        )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["target_record_id"] == second.json()["target_record_id"]


def test_push_valid_records_retries_503_and_persists_attempts(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'push.db'}")) as client:
        token = _token(client)
        migration_id = _seed_migration_with_records(["E001", "E-FAIL-503"])
        response = client.post(
            f"/api/v1/migrations/{migration_id}/push",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["pushed"] == 2
    retry_result = next(item for item in body["results"] if item["employee_id"] == "E-FAIL-503")
    assert retry_result["status"] == PushStatus.SUCCEEDED
    assert retry_result["attempts"] == 3

    with SessionLocal() as db:
        attempts = db.scalars(
            select(PushAttempt).where(PushAttempt.migration_id == migration_id)
        ).all()
        target_records = db.scalars(select(MockTargetRecord)).all()

    assert len(attempts) == 4
    assert len(target_records) == 2


def test_same_employee_can_be_pushed_from_different_migrations(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'repeat_employee.db'}")) as client:
        token = _token(client)
        first_migration_id = _seed_migration_with_records(["E001"])
        second_migration_id = _seed_migration_with_records(["E001"])
        first = client.post(
            f"/api/v1/migrations/{first_migration_id}/push",
            headers={"Authorization": f"Bearer {token}"},
        )
        second = client.post(
            f"/api/v1/migrations/{second_migration_id}/push",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    first_target = first.json()["results"][0]["target_record_id"]
    second_target = second.json()["results"][0]["target_record_id"]
    assert first_target != second_target

    with SessionLocal() as db:
        target_records = db.scalars(select(MockTargetRecord)).all()

    assert len(target_records) == 2


def test_push_422_is_permanent_failure_without_retry(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'permanent.db'}")) as client:
        token = _token(client)
        migration_id = _seed_migration_with_records(["E-FAIL-422"])
        response = client.post(
            f"/api/v1/migrations/{migration_id}/push",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == PushStatus.FAILED_PERMANENT
    assert result["attempts"] == 1
    assert result["http_status"] == 422


def test_rollback_marks_successful_pushes_as_rolled_back(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'rollback.db'}")) as client:
        token = _token(client)
        migration_id = _seed_migration_with_records(["E001", "E002"])
        push = client.post(
            f"/api/v1/migrations/{migration_id}/push",
            headers={"Authorization": f"Bearer {token}"},
        )
        rollback = client.post(
            f"/api/v1/migrations/{migration_id}/rollback",
            headers={"Authorization": f"Bearer {token}"},
        )
        second_rollback = client.post(
            f"/api/v1/migrations/{migration_id}/rollback",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert push.status_code == 200
    assert rollback.status_code == 200
    assert rollback.json()["rolled_back"] == 2
    assert second_rollback.status_code == 200
    assert second_rollback.json()["rolled_back"] == 0

    with SessionLocal() as db:
        migration = db.get(Migration, migration_id)
        target_records = db.scalars(select(MockTargetRecord)).all()
        rolled_back_attempts = db.scalars(
            select(PushAttempt).where(PushAttempt.status == PushStatus.ROLLED_BACK)
        ).all()

    assert migration is not None
    assert migration.status == MigrationStatus.ROLLED_BACK
    assert all(record.is_deleted for record in target_records)
    assert len(rolled_back_attempts) == 2


def test_push_preview_is_read_only_and_masks_sensitive_values(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'preview.db'}")) as client:
        token = _token(client)
        migration_id = _seed_migration_with_records(["E001"], include_sensitive=True)
        before = client.get(
            f"/api/v1/migrations/{migration_id}/push-preview",
            headers={"Authorization": f"Bearer {token}"},
        )
        after = client.get(
            f"/api/v1/migrations/{migration_id}/records",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert before.status_code == 200
    assert before.json()["ready_count"] == 1
    assert before.json()["blocked_count"] == 0
    preview_data = before.json()["records"][0]["data"]
    record_data = after.json()[0]["data"]
    assert preview_data["annual_salary"].startswith("*")
    assert record_data["annual_salary"].startswith("*")
    assert preview_data["bank_account_number"].startswith("*")

    with SessionLocal() as db:
        attempts = db.scalars(select(PushAttempt).where(PushAttempt.migration_id == migration_id)).all()
        target_records = db.scalars(select(MockTargetRecord)).all()

    assert attempts == []
    assert target_records == []


def test_rollback_preview_is_read_only(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'rollback-preview.db'}")) as client:
        token = _token(client)
        migration_id = _seed_migration_with_records(["E001"])
        push = client.post(
            f"/api/v1/migrations/{migration_id}/push",
            headers={"Authorization": f"Bearer {token}"},
        )
        preview = client.get(
            f"/api/v1/migrations/{migration_id}/rollback-preview",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert push.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["removable_count"] == 1
    assert preview.json()["records"][0]["action"] == "Remove target employee"

    with SessionLocal() as db:
        target_records = db.scalars(select(MockTargetRecord)).all()
        attempts = db.scalars(select(PushAttempt).where(PushAttempt.migration_id == migration_id)).all()

    assert all(not record.is_deleted for record in target_records)
    assert all(attempt.status == PushStatus.SUCCEEDED for attempt in attempts)


def test_run_metrics_reports_scores_and_llm_unknown_tokens(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'metrics.db'}")) as client:
        token = _token(client)
        migration_id = _seed_migration_with_records(["E001", "E002"], include_mapping=True)
        response = client.get(
            f"/api/v1/migrations/{migration_id}/run-metrics",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["readiness_score"] == 100
    assert body["agent_score"] >= 90
    assert body["ready_to_push"] == 2
    assert body["llm"]["used"] is True
    assert body["llm"]["total_tokens"] is None


def test_audit_response_masks_sensitive_metadata(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'audit-mask.db'}")) as client:
        token = _token(client)
        migration_id = _seed_migration_with_records(["E001"])
        with SessionLocal() as db:
            AuditService(db).append(
                AuditEventCreate(
                    migration_id=migration_id,
                    actor_type="SYSTEM",
                    event_type="SENSITIVE_CHECK",
                    entity_type="canonical_record",
                    metadata={"annual_salary": 1250000, "phone": "9876510001"},
                )
            )
        response = client.get(
            f"/api/v1/migrations/{migration_id}/audit-events",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    metadata = response.json()[-1]["metadata"]
    assert metadata["annual_salary"].startswith("*")
    assert metadata["phone"].startswith("*")


def _token(client: TestClient) -> str:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "consultant", "password": "demo-password"},
    )
    return login.json()["access_token"]


def _seed_migration_with_records(
    employee_ids: list[str],
    include_sensitive: bool = False,
    include_mapping: bool = False,
) -> str:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "consultant"))
        assert user is not None
        migration = Migration(
            status=MigrationStatus.VALIDATING,
            created_by=user.id,
            target_schema_version="employee-v1",
            current_node="validate_records",
            valid_records=len(employee_ids),
        )
        db.add(migration)
        db.flush()
        if include_mapping:
            from app.core.enums import MappingDecision
            from app.models.mapping import Mapping
            from app.models.source_file import SourceFile

            source = SourceFile(
                migration_id=migration.id,
                original_name="employees.csv",
                stored_path="storage/employees.csv",
                file_type="csv",
                size_bytes=100,
                checksum_sha256="fixture",
                row_count=len(employee_ids),
            )
            db.add(source)
            db.flush()
            db.add(
                Mapping(
                    migration_id=migration.id,
                    source_file_id=source.id,
                    source_column="emp_mail",
                    target_field="email",
                    semantic_score=0.95,
                    name_score=0.9,
                    type_score=1.0,
                    value_score=1.0,
                    final_score=0.96,
                    decision=MappingDecision.AUTO_APPROVED,
                    decision_source="LLM",
                    reasoning="Suggested by LLM.",
                    alternatives_json="[]",
                )
            )
        for employee_id in employee_ids:
            data = {
                "employee_id": employee_id,
                "full_name": f"Employee {employee_id}",
                "email": f"{employee_id.lower()}@example.com",
                "joining_date": "2022-04-01",
            }
            if include_sensitive:
                data.update(
                    {
                        "annual_salary": 1250000,
                        "bank_account_number": "123456789012",
                        "phone": "9876510001",
                    }
                )
            db.add(
                CanonicalRecord(
                    migration_id=migration.id,
                    employee_id=employee_id,
                    data_json=json.dumps(data),
                    provenance_json="{}",
                    validation_status=ValidationStatus.VALID,
                    issues_json="[]",
                )
            )
        db.commit()
        return migration.id
