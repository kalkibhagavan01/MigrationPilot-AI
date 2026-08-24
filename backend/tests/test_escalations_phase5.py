import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.enums import EscalationStatus, MigrationStatus, UserRole, ValidationStatus
from app.db.session import SessionLocal
from app.main import create_app
from app.models.canonical_record import CanonicalRecord
from app.models.escalation import Escalation
from app.models.migration import Migration
from app.models.user import User


def test_compensation_escalation_is_visible_to_demo_admin(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'policy.db'}")) as client:
        migration_id = _seed_salary_issue()
        consultant_token = _token(client, "consultant")
        comp_token = _token(client, "compensation_manager")

        build = client.post(
            f"/api/v1/migrations/{migration_id}/escalations/build",
            headers={"Authorization": f"Bearer {consultant_token}"},
        )
        consultant_list = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {consultant_token}"},
        )
        comp_list = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {comp_token}"},
        )

    assert build.status_code == 200
    assert build.json()["created"] == 1
    assert len(consultant_list.json()) == 1
    assert consultant_list.json()[0]["context"]["value"] == "99999999"
    comp_body = comp_list.json()
    assert len(comp_body) == 1
    assert comp_body[0]["required_role"] == UserRole.COMPENSATION_MANAGER
    assert comp_body[0]["context"]["value"] == "99999999"


def test_direct_sensitive_escalation_access_allowed_for_demo_admin(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'direct.db'}")) as client:
        migration_id = _seed_salary_issue()
        consultant_token = _token(client, "consultant")
        client.post(
            f"/api/v1/migrations/{migration_id}/escalations/build",
            headers={"Authorization": f"Bearer {consultant_token}"},
        )
        with SessionLocal() as db:
            escalation = db.scalar(select(Escalation).where(Escalation.migration_id == migration_id))
            assert escalation is not None

        response = client.get(
            f"/api/v1/escalations/{escalation.id}",
            headers={"Authorization": f"Bearer {consultant_token}"},
        )

    assert response.status_code == 200
    assert response.json()["context"]["value"] == "99999999"


def test_compensation_manager_resolves_and_second_resolution_gets_409(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'resolve.db'}")) as client:
        migration_id = _seed_salary_issue()
        comp_token = _token(client, "compensation_manager")
        client.post(
            f"/api/v1/migrations/{migration_id}/escalations/build",
            headers={"Authorization": f"Bearer {comp_token}"},
        )
        escalation = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {comp_token}"},
        ).json()[0]

        first = client.post(
            f"/api/v1/escalations/{escalation['id']}/resolve",
            headers={"Authorization": f"Bearer {comp_token}"},
            json={"action": "APPROVE", "resolution": {"accepted": True}},
        )
        second = client.post(
            f"/api/v1/escalations/{escalation['id']}/resolve",
            headers={"Authorization": f"Bearer {comp_token}"},
            json={"action": "APPROVE", "resolution": {"accepted": True}},
        )

    assert first.status_code == 200
    assert first.json()["status"] == EscalationStatus.RESOLVED
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ESCALATION_ALREADY_RESOLVED"

    with SessionLocal() as db:
        migration = db.get(Migration, migration_id)
        assert migration is not None
        assert migration.status == MigrationStatus.VALIDATING
        assert migration.current_node == "validate_records"


def test_approval_marks_review_record_valid_for_push(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'approve.db'}")) as client:
        migration_id = _seed_salary_issue()
        token = _token(client, "admin")
        client.post(
            f"/api/v1/migrations/{migration_id}/escalations/build",
            headers={"Authorization": f"Bearer {token}"},
        )
        escalation = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {token}"},
        ).json()[0]

        assert escalation["context"]["summary"] == "Annual Salary looks unusual"
        assert "human check" in escalation["context"]["reason"]
        assert escalation["context"]["recommended_action_text"].startswith("If the value is correct")
        assert {"label": "Current value", "value": "99999999"} in escalation["context"]["evidence"]

        response = client.post(
            f"/api/v1/escalations/{escalation['id']}/resolve",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "APPROVE", "resolution": {"accepted": True}},
        )
        push = client.post(
            f"/api/v1/migrations/{migration_id}/push",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert push.status_code == 200
    assert push.json()["pushed"] == 1

    with SessionLocal() as db:
        record = db.scalar(select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id))
        assert record is not None
        assert record.validation_status == ValidationStatus.VALID
        assert json.loads(record.issues_json) == []


def test_correction_updates_canonical_record_and_clears_issue(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'correct.db'}")) as client:
        migration_id = _seed_salary_issue()
        token = _token(client, "admin")
        client.post(
            f"/api/v1/migrations/{migration_id}/escalations/build",
            headers={"Authorization": f"Bearer {token}"},
        )
        escalation = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {token}"},
        ).json()[0]

        response = client.post(
            f"/api/v1/escalations/{escalation['id']}/resolve",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "action": "CORRECT",
                "resolution": {"field": "annual_salary", "corrected_value": "1800000"},
            },
        )

    assert response.status_code == 200

    with SessionLocal() as db:
        record = db.scalar(select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id))
        assert record is not None
        assert json.loads(record.data_json)["annual_salary"] == "1800000"
        assert record.validation_status == ValidationStatus.VALID
        assert json.loads(record.issues_json) == []


def test_sensitive_valid_record_does_not_create_approval_work(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'noapproval.db'}")) as client:
        migration_id = _seed_valid_salary_record()
        token = _token(client, "consultant")
        response = client.post(
            f"/api/v1/migrations/{migration_id}/escalations/build",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["created"] == 0


def test_missing_required_field_review_is_operator_friendly_and_can_send_to_hr(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'hr_info.db'}")) as client:
        migration_id = _seed_missing_joining_date()
        token = _token(client, "admin")
        client.post(
            f"/api/v1/migrations/{migration_id}/escalations/build",
            headers={"Authorization": f"Bearer {token}"},
        )
        escalation = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {token}"},
        ).json()[0]

        assert escalation["context"]["summary"] == "Joining Date is missing or invalid"
        assert {"label": "Issue", "value": "Joining Date is missing."} in escalation["context"]["evidence"]

        sent = client.post(
            f"/api/v1/escalations/{escalation['id']}/resolve",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "action": "SEND_TO_HR",
                "resolution": {"field": "joining_date", "comment": "Please confirm joining date."},
            },
        )
        still_open = client.get(
            f"/api/v1/migrations/{migration_id}/escalations",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert sent.status_code == 200
    assert sent.json()["status"] == EscalationStatus.OPEN
    assert len(still_open.json()) == 1


def _token(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "demo-password"},
    )
    return response.json()["access_token"]


def _seed_salary_issue() -> str:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "consultant"))
        assert user is not None
        migration = Migration(
            status=MigrationStatus.VALIDATING,
            created_by=user.id,
            target_schema_version="employee-v1",
            current_node="validate_records",
        )
        db.add(migration)
        db.flush()
        db.add(
            CanonicalRecord(
                migration_id=migration.id,
                employee_id="E-FAIL-503",
                data_json=json.dumps(
                    {
                        "employee_id": "E-FAIL-503",
                        "full_name": "Retry Target",
                        "email": "retry@example.com",
                        "joining_date": "2019-08-19",
                        "annual_salary": "99999999",
                        "currency": "INR",
                        "pay_frequency": "ANNUAL",
                    }
                ),
                provenance_json="{}",
                validation_status=ValidationStatus.NEEDS_REVIEW,
                issues_json=json.dumps(
                    [
                        {
                            "type": "NUMERIC_OUTLIER",
                            "field": "annual_salary",
                            "value": "99999999",
                        }
                    ]
                ),
            )
        )
        db.commit()
        return migration.id


def _seed_valid_salary_record() -> str:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "consultant"))
        assert user is not None
        migration = Migration(
            status=MigrationStatus.VALIDATING,
            created_by=user.id,
            target_schema_version="employee-v1",
            current_node="validate_records",
        )
        db.add(migration)
        db.flush()
        db.add(
            CanonicalRecord(
                migration_id=migration.id,
                employee_id="E001",
                data_json=json.dumps(
                    {
                        "employee_id": "E001",
                        "full_name": "Asha Rao",
                        "email": "asha@example.com",
                        "joining_date": "2022-04-01",
                        "annual_salary": "1000000",
                        "currency": "INR",
                        "pay_frequency": "ANNUAL",
                    }
                ),
                provenance_json="{}",
                validation_status=ValidationStatus.VALID,
                issues_json="[]",
            )
        )
        db.commit()
        return migration.id


def _seed_missing_joining_date() -> str:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "consultant"))
        assert user is not None
        migration = Migration(
            status=MigrationStatus.VALIDATING,
            created_by=user.id,
            target_schema_version="employee-v1",
            current_node="validate_records",
        )
        db.add(migration)
        db.flush()
        db.add(
            CanonicalRecord(
                migration_id=migration.id,
                employee_id="E002",
                data_json=json.dumps(
                    {
                        "employee_id": "E002",
                        "full_name": "Rohan Mehta",
                        "email": "rohan@example.com",
                        "manager_id": "E010",
                    }
                ),
                provenance_json=json.dumps(
                    {
                        "employee_id": {
                            "source_file": "employees_master.xlsx",
                            "source_column": "employee_id",
                            "source_row": 3,
                        }
                    }
                ),
                validation_status=ValidationStatus.INVALID,
                issues_json=json.dumps(
                    [
                        {
                            "type": "VALIDATION_FAILED",
                            "reason": (
                                "1 validation error for EmployeeTarget\njoining_date\n"
                                "  Field required [type=missing]"
                            ),
                        }
                    ]
                ),
            )
        )
        db.commit()
        return migration.id
