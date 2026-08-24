from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from app.core.enums import MigrationStatus
from app.db.session import SessionLocal
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.column_profile import ColumnProfile
from app.models.migration import Migration
from app.models.source_file import SourceFile


def make_client(database_url: str) -> TestClient:
    return TestClient(create_app(database_url=database_url))


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "consultant", "password": "demo-password"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_create_migration_ingests_and_profiles_csv(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'migration.db'}") as client:
        response = client.post(
            "/api/v1/migrations",
            headers=auth_headers(client),
            files={
                "files": (
                    "employees.csv",
                    b"employee_id,email,joining_date\n0007,LEENA@example.com,2024-01-10\n",
                    "text/csv",
                )
            },
            data={"target_schema_version": "employee-v1"},
        )

        assert response.status_code == 201
        body = response.json()
        migration_id = body["migration_id"]
        assert body["status"] == MigrationStatus.PROFILING
        assert body["profiles_created"] == 3
        detail = client.get(f"/api/v1/migrations/{migration_id}", headers=auth_headers(client))

    assert detail.status_code == 200
    assert detail.json()["progress"] == {"files": 1, "records": 1, "profiles": 3}

    with SessionLocal() as db:
        migration = db.get(Migration, migration_id)
        source_file = db.scalar(select(SourceFile).where(SourceFile.migration_id == migration_id))
        employee_profile = db.scalar(
            select(ColumnProfile).where(ColumnProfile.column_name == "employee_id")
        )
        audit_events = db.scalars(
            select(AuditEvent).where(AuditEvent.migration_id == migration_id)
        ).all()

    assert migration is not None
    assert migration.current_node == "profile_files"
    assert source_file is not None
    assert source_file.row_count == 1
    assert employee_profile is not None
    assert '"0007"' in employee_profile.sample_values_json
    assert {event.event_type for event in audit_events} == {"FILE_INGESTED", "FILE_PROFILED"}


def test_create_migration_ingests_and_profiles_xlsx(tmp_path) -> None:
    workbook_bytes = _workbook_bytes()
    with make_client(f"sqlite:///{tmp_path / 'xlsx.db'}") as client:
        response = client.post(
            "/api/v1/migrations",
            headers=auth_headers(client),
            files={
                "files": (
                    "contacts.xlsx",
                    workbook_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["files"][0]["row_count"] == 2
    assert body["profiles_created"] == 3


def test_unsupported_file_type_returns_415(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'unsupported.db'}") as client:
        response = client.post(
            "/api/v1/migrations",
            headers=auth_headers(client),
            files={"files": ("payload.zip", b"not allowed", "application/zip")},
        )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_missing_files_returns_400(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'nofiles.db'}") as client:
        response = client.post(
            "/api/v1/migrations",
            headers=auth_headers(client),
            data={"target_schema_version": "employee-v1"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NO_FILES"


def test_migration_events_stream_returns_status_event(tmp_path) -> None:
    with make_client(f"sqlite:///{tmp_path / 'events.db'}") as client:
        headers = auth_headers(client)
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
        response = client.get(f"/api/v1/migrations/{migration_id}/events", headers=headers)

    assert response.status_code == 200
    assert "event: migration.status" in response.text
    assert migration_id in response.text


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "contacts"
    sheet.append(["employee_code", "mail_id", "mobile_number"])
    sheet.append(["E001", "ASHA@example.com", "+91 98765 10001"])
    sheet.append(["E002", "rohan@example.com", "+91 98765 10002"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
