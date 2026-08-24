from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.enums import MappingDecision
from app.db.session import SessionLocal
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.mapping import Mapping


def test_generate_mappings_endpoint_persists_mapping_and_audit(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'mapping_api.db'}")) as client:
        token = _token(client)
        upload = client.post(
            "/api/v1/migrations",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "files": (
                    "employees.csv",
                    b"Emp No,email,blood_group\nE001,asha@example.com,O+\n",
                    "text/csv",
                )
            },
        )
        migration_id = upload.json()["migration_id"]
        response = client.post(
            f"/api/v1/migrations/{migration_id}/mappings",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    decisions = {item["source_column"]: item["decision"] for item in body["mappings"]}
    assert decisions["Emp No"] == MappingDecision.AUTO_APPROVED
    assert decisions["email"] == MappingDecision.AUTO_APPROVED
    assert decisions["blood_group"] == MappingDecision.NEEDS_REVIEW

    with SessionLocal() as db:
        mappings = db.scalars(select(Mapping).where(Mapping.migration_id == migration_id)).all()
        audit_events = db.scalars(
            select(AuditEvent).where(AuditEvent.migration_id == migration_id)
        ).all()

    assert len(mappings) == 3
    assert "MAPPING_AUTO_APPROVED" in {event.event_type for event in audit_events}
    assert "MAPPING_ESCALATED" in {event.event_type for event in audit_events}


def _token(client: TestClient) -> str:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "consultant", "password": "demo-password"},
    )
    return login.json()["access_token"]
