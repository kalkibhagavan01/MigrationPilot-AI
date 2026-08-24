from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.core.enums import EscalationStatus, MappingDecision, MigrationStatus
from app.db.session import SessionLocal
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.canonical_record import CanonicalRecord
from app.models.escalation import Escalation
from app.models.mapping import Mapping
from app.models.migration import Migration
from app.models.push_attempt import PushAttempt


def test_start_runs_happy_path_and_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'happy-workflow.db'}")) as client:
        token = _token(client)
        migration_id = _upload_happy_files(client, token)

        first = client.post(
            f"/api/v1/migrations/{migration_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        second = client.post(
            f"/api/v1/migrations/{migration_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        mappings_reload = client.post(
            f"/api/v1/migrations/{migration_id}/mappings",
            headers={"Authorization": f"Bearer {token}"},
        )
        summary_after_reload = client.get(
            f"/api/v1/migrations/{migration_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert first.status_code == 200
    assert first.json()["status"] == MigrationStatus.COMPLETED
    assert first.json()["open_reviews"] == 0
    assert first.json()["pushed"] == 2
    assert second.status_code == 200
    assert second.json()["status"] == MigrationStatus.COMPLETED
    assert mappings_reload.status_code == 200
    assert summary_after_reload.json()["status"] == MigrationStatus.COMPLETED

    with SessionLocal() as db:
        mappings = db.scalars(select(Mapping).where(Mapping.migration_id == migration_id)).all()
        records = db.scalars(
            select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id)
        ).all()
        attempts = db.scalars(select(PushAttempt).where(PushAttempt.migration_id == migration_id)).all()
        mapping_audits = db.scalars(
            select(AuditEvent).where(
                AuditEvent.migration_id == migration_id,
                AuditEvent.event_type.in_(["MAPPING_AUTO_APPROVED", "MAPPING_ESCALATED"]),
            )
        ).all()

    assert len(mappings) == 5
    assert len(records) == 2
    assert len(attempts) == 2
    assert len(mapping_audits) == 5


def test_start_stops_for_mapping_review_before_canonicalization(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'mapping-review.db'}")) as client:
        token = _token(client)
        migration_id = _upload_mapping_review_file(client, token)

        response = client.post(
            f"/api/v1/migrations/{migration_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        repeated = client.post(
            f"/api/v1/migrations/{migration_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        reviews = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == MigrationStatus.WAITING_FOR_REVIEW
    assert response.json()["open_reviews"] == 1
    assert response.json()["records"] == 0
    assert repeated.status_code == 200
    assert repeated.json()["status"] == MigrationStatus.WAITING_FOR_REVIEW
    assert repeated.json()["records"] == 0
    assert reviews.status_code == 200
    assert reviews.json()[0]["issue_type"] == "MAPPING_AMBIGUITY"
    assert reviews.json()[0]["context"]["source_column"] == "legacy_grade_code"


def test_mapping_review_resolution_allows_workflow_to_continue(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'mapping-resume.db'}")) as client:
        token = _token(client)
        migration_id = _upload_mapping_review_file(client, token)
        client.post(
            f"/api/v1/migrations/{migration_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        review = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {token}"},
        ).json()[0]
        resolved = client.post(
            f"/api/v1/escalations/{review['id']}/resolve",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "REJECT", "resolution": {"reason": "No target field exists."}},
        )
        stale = client.post(
            f"/api/v1/escalations/{review['id']}/resolve",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "REJECT", "resolution": {"reason": "Already handled."}},
        )

    assert resolved.status_code == 200
    assert resolved.json()["status"] == EscalationStatus.REJECTED
    assert stale.status_code == 409

    with SessionLocal() as db:
        migration = db.get(Migration, migration_id)
        mapping = db.scalar(
            select(Mapping).where(
                Mapping.migration_id == migration_id,
                Mapping.source_column == "legacy_grade_code",
            )
        )
        records = db.scalars(
            select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id)
        ).all()
        attempts = db.scalars(select(PushAttempt).where(PushAttempt.migration_id == migration_id)).all()

    assert migration is not None
    assert migration.status == MigrationStatus.COMPLETED
    assert len(records) == 1
    assert len(attempts) == 1
    assert mapping is not None
    assert mapping.decision == MappingDecision.REJECTED
    assert mapping.target_field is None


def test_rejected_data_review_blocks_push_when_no_valid_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'reject-data-review.db'}")) as client:
        token = _token(client)
        migration_id = _upload_missing_required_email_file(client, token)
        started = client.post(
            f"/api/v1/migrations/{migration_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        review = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {token}"},
        ).json()[0]
        resolved = client.post(
            f"/api/v1/escalations/{review['id']}/resolve",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "REJECT", "resolution": {"reason": "Source data is incomplete."}},
        )

    assert started.status_code == 200
    assert started.json()["status"] == MigrationStatus.WAITING_FOR_REVIEW
    assert resolved.status_code == 200
    assert resolved.json()["status"] == EscalationStatus.REJECTED

    with SessionLocal() as db:
        migration = db.get(Migration, migration_id)
        attempts = db.scalars(select(PushAttempt).where(PushAttempt.migration_id == migration_id)).all()
        valid_records = db.scalars(
            select(CanonicalRecord).where(
                CanonicalRecord.migration_id == migration_id,
                CanonicalRecord.validation_status == "VALID",
            )
        ).all()

    assert migration is not None
    assert migration.status == MigrationStatus.BLOCKED
    assert migration.current_node == "push_records_node"
    assert attempts == []
    assert valid_records == []


def test_corrected_mapping_resolution_continues_to_push(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'corrected-mapping.db'}")) as client:
        token = _token(client)
        migration_id = _upload_correctable_mapping_file(client, token)
        started = client.post(
            f"/api/v1/migrations/{migration_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        review = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {token}"},
        ).json()[0]
        resolved = client.post(
            f"/api/v1/escalations/{review['id']}/resolve",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "CORRECT", "resolution": {"target_field": "email"}},
        )

    assert started.status_code == 200
    assert started.json()["status"] == MigrationStatus.WAITING_FOR_REVIEW
    assert resolved.status_code == 200
    assert resolved.json()["status"] == EscalationStatus.RESOLVED

    with SessionLocal() as db:
        migration = db.get(Migration, migration_id)
        mapping = db.scalar(
            select(Mapping).where(
                Mapping.migration_id == migration_id,
                Mapping.source_column == "contact_address",
            )
        )
        records = db.scalars(
            select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id)
        ).all()
        attempts = db.scalars(select(PushAttempt).where(PushAttempt.migration_id == migration_id)).all()

    assert migration is not None
    assert migration.status == MigrationStatus.COMPLETED
    assert mapping is not None
    assert mapping.decision == MappingDecision.MANUALLY_CORRECTED
    assert mapping.target_field == "email"
    assert len(records) == 1
    assert len(attempts) == 1


def test_records_and_activity_are_reloadable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'reloadable.db'}")) as client:
        token = _token(client)
        migration_id = _upload_happy_files(client, token)
        client.post(
            f"/api/v1/migrations/{migration_id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )

        records = client.get(
            f"/api/v1/migrations/{migration_id}/records",
            headers={"Authorization": f"Bearer {token}"},
        )
        activity = client.get(
            f"/api/v1/migrations/{migration_id}/activity",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert records.status_code == 200
    assert len(records.json()) == 2
    assert records.json()[0]["push_status"] == "SUCCEEDED"
    assert activity.status_code == 200
    assert any(item["message"] == "Started migration workflow" for item in activity.json())


def _token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "consultant", "password": "demo-password"},
    )
    return response.json()["access_token"]


def _upload_happy_files(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/migrations",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            (
                "files",
                (
                    "employees_master.csv",
                    (
                        "employee_id,full_name,joining_date\n"
                        "E001,Asha Rao,2022-04-01\n"
                        "E002,Rohan Mehta,2021-05-04\n"
                    ).encode(),
                    "text/csv",
                ),
            ),
            (
                "files",
                (
                    "employee_contacts.csv",
                    (
                        "employee_id,email\n"
                        "E001,asha@example.com\n"
                        "E002,rohan@example.com\n"
                    ).encode(),
                    "text/csv",
                ),
            ),
        ],
    )
    assert response.status_code == 201
    return response.json()["migration_id"]


def _upload_mapping_review_file(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/migrations",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            (
                "files",
                (
                    "employees_master.csv",
                    (
                        "employee_id,full_name,email,joining_date,legacy_grade_code\n"
                        "E001,Asha Rao,asha@example.com,2022-04-01,G7\n"
                    ).encode(),
                    "text/csv",
                ),
            )
        ],
    )
    assert response.status_code == 201
    return response.json()["migration_id"]


def _upload_missing_required_email_file(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/migrations",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            (
                "files",
                (
                    "employees_master.csv",
                    (
                        "employee_id,full_name,joining_date\n"
                        "E001,Asha Rao,2022-04-01\n"
                    ).encode(),
                    "text/csv",
                ),
            )
        ],
    )
    assert response.status_code == 201
    return response.json()["migration_id"]


def _upload_correctable_mapping_file(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/migrations",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            (
                "files",
                (
                    "employees_master.csv",
                    (
                        "employee_id,full_name,contact_address,joining_date\n"
                        "E001,Asha Rao,asha@example.com,2022-04-01\n"
                    ).encode(),
                    "text/csv",
                ),
            )
        ],
    )
    assert response.status_code == 201
    return response.json()["migration_id"]
