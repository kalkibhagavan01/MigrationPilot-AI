import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.enums import MigrationStatus, ValidationStatus
from app.db.session import SessionLocal
from app.main import create_app
from app.models.canonical_record import CanonicalRecord
from app.models.migration import Migration
from app.models.user import User


def test_audit_endpoint_returns_migration_timeline(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'audit_api.db'}")) as client:
        headers = _headers(client, "consultant")
        upload = client.post(
            "/api/v1/migrations",
            headers=headers,
            files={
                "files": (
                    "employees.csv",
                    b"employee_id,email,joining_date\nE001,asha@example.com,2024-01-10\n",
                    "text/csv",
                )
            },
        )
        migration_id = upload.json()["migration_id"]
        response = client.get(f"/api/v1/migrations/{migration_id}/audit-events", headers=headers)

    assert response.status_code == 200
    events = response.json()
    assert [event["event_type"] for event in events] == ["FILE_INGESTED", "FILE_PROFILED"]
    assert events[0]["metadata"]["file_name"] == "employees.csv"


def test_ops_metrics_and_kill_switch_status(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'ops.db'}")) as client:
        headers = _headers(client, "consultant")
        response = client.get("/api/v1/ops/metrics", headers=headers)
        kill_switch = client.get("/api/v1/ops/kill-switch", headers=headers)

    assert response.status_code == 200
    assert response.json()["kill_switch_enabled"] is False
    assert kill_switch.status_code == 200
    assert kill_switch.json() == {"enabled": False, "reason": None}


def test_kill_switch_blocks_new_migration_start(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'kill_start.db'}")) as client:
        admin_headers = _headers(client, "admin")
        consultant_headers = _headers(client, "consultant")
        toggle = client.put(
            "/api/v1/ops/kill-switch",
            headers=admin_headers,
            json={"enabled": True, "reason": "maintenance window"},
        )
        response = client.post(
            "/api/v1/migrations",
            headers=consultant_headers,
            files={
                "files": (
                    "employees.csv",
                    b"employee_id,email,joining_date\nE001,asha@example.com,2024-01-10\n",
                    "text/csv",
                )
            },
        )

    assert toggle.status_code == 200
    assert response.status_code == 423
    assert response.json()["error"]["code"] == "KILL_SWITCH_ACTIVE"


def test_kill_switch_blocks_push_but_allows_rollback(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'kill_push.db'}")) as client:
        consultant_headers = _headers(client, "consultant")
        migration_id = _seed_migration_with_records(["E001"])
        ok_push = client.post(f"/api/v1/migrations/{migration_id}/push", headers=consultant_headers)
        admin_headers = _headers(client, "admin")
        client.put(
            "/api/v1/ops/kill-switch",
            headers=admin_headers,
            json={"enabled": True, "reason": "incident"},
        )
        blocked_push = client.post(f"/api/v1/migrations/{migration_id}/push", headers=consultant_headers)
        rollback = client.post(f"/api/v1/migrations/{migration_id}/rollback", headers=consultant_headers)

    assert ok_push.status_code == 200
    assert blocked_push.status_code == 423
    assert blocked_push.json()["error"]["code"] == "KILL_SWITCH_ACTIVE"
    assert rollback.status_code == 200
    assert rollback.json()["rolled_back"] == 1


def _headers(client: TestClient, username: str) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "demo-password"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_migration_with_records(employee_ids: list[str]) -> str:
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
        for employee_id in employee_ids:
            db.add(
                CanonicalRecord(
                    migration_id=migration.id,
                    employee_id=employee_id,
                    data_json=json.dumps(
                        {
                            "employee_id": employee_id,
                            "full_name": f"Employee {employee_id}",
                            "email": f"{employee_id.lower()}@example.com",
                            "joining_date": "2022-04-01",
                        }
                    ),
                    provenance_json="{}",
                    validation_status=ValidationStatus.VALID,
                    issues_json="[]",
                )
            )
        db.commit()
        return migration.id
