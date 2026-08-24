import json
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.enums import ValidationStatus
from app.db.session import SessionLocal
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.canonical_record import CanonicalRecord
from app.services.canonicalization import CanonicalizationService, _assign_mapped_value
from app.services.cleaning import clean_value


def test_cleaning_normalizes_email_and_explicit_date() -> None:
    email, email_issues = clean_value("email", " ASHA@EXAMPLE.COM ")
    date_value, date_issues = clean_value("joining_date", "10-01-2024")

    assert email == "asha@example.com"
    assert email_issues == []
    assert date_value == "2024-01-10"
    assert date_issues == []


def test_cleaning_flags_ambiguous_date() -> None:
    value, issues = clean_value("joining_date", "03/04/2025")

    assert value is None
    assert issues == [
        {"type": "AMBIGUOUS_DATE_FORMAT", "field": "joining_date", "value": "03/04/2025"}
    ]


def test_canonicalize_endpoint_cleans_reconciles_validates_and_audits(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'phase4.db'}")) as client:
        token = _token(client)
        migration_id = _upload_three_files(client, token)
        mapping_response = client.post(
            f"/api/v1/migrations/{migration_id}/mappings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert mapping_response.status_code == 200

        response = client.post(
            f"/api/v1/migrations/{migration_id}/canonicalize",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["records_created"] == 6
    assert body["valid_records"] == 4
    assert body["invalid_records"] == 1
    assert body["review_records"] == 1

    with SessionLocal() as db:
        records = db.scalars(
            select(CanonicalRecord).where(CanonicalRecord.migration_id == migration_id)
        ).all()
        audit_events = db.scalars(
            select(AuditEvent).where(AuditEvent.migration_id == migration_id)
        ).all()

    by_employee = {record.employee_id: record for record in records}
    e001_data = json.loads(by_employee["E001"].data_json)
    e004_data = json.loads(by_employee["E004"].data_json)
    e005_issues = json.loads(by_employee["E005"].issues_json)
    outlier_issues = json.loads(by_employee["E-FAIL-503"].issues_json)

    assert e001_data["email"] == "asha@example.com"
    assert e001_data["joining_date"] == "2022-04-01"
    assert e004_data["department"] == "Engineering"
    assert by_employee["E005"].validation_status == ValidationStatus.INVALID
    assert any(issue["type"] == "VALIDATION_FAILED" for issue in e005_issues)
    assert by_employee["E-FAIL-503"].validation_status == ValidationStatus.NEEDS_REVIEW
    assert any(issue["type"] == "NUMERIC_OUTLIER" for issue in outlier_issues)

    event_types = {event.event_type for event in audit_events}
    assert "CONFLICT_RESOLVED_BY_PRECEDENCE" in event_types
    assert "EXACT_DUPLICATE_REMOVED" in event_types


def test_hike_percentage_outlier_creates_review_issue(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'hike-outlier.db'}")):
        with SessionLocal() as db:
            merged = {
                "E001": {"data": {"hike_percentage": Decimal("8")}, "issues": []},
                "E002": {"data": {"hike_percentage": Decimal("9")}, "issues": []},
                "E003": {"data": {"hike_percentage": Decimal("10")}, "issues": []},
                "E004": {"data": {"hike_percentage": Decimal("11")}, "issues": []},
                "E005": {"data": {"hike_percentage": Decimal("60")}, "issues": []},
            }

            CanonicalizationService(db)._detect_numeric_outliers(merged)

    assert merged["E005"]["issues"] == [
        {"type": "NUMERIC_OUTLIER", "field": "hike_percentage", "value": "60"}
    ]


def test_same_source_employee_conflict_creates_review_issue(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'same-source-conflict.db'}")):
        with SessionLocal() as db:
            rows = [
                {
                    "data": {"employee_id": "E2004", "department": "Sales"},
                    "provenance": {
                        "employee_id": _source("employees_master.csv", "employee_id", 2),
                        "department": _source("employees_master.csv", "department", 2),
                    },
                    "issues": [],
                },
                {
                    "data": {"employee_id": "E2004", "department": "Revenue Operations"},
                    "provenance": {
                        "employee_id": _source("employees_master.csv", "employee_id", 3),
                        "department": _source("employees_master.csv", "department", 3),
                    },
                    "issues": [],
                },
            ]

            merged = CanonicalizationService(db)._merge_rows("migration-id", rows)

    issues = merged["E2004"]["issues"]
    assert issues[0]["type"] == "SOURCE_VALUE_CONFLICT"
    assert issues[0]["field"] == "department"
    assert issues[0]["existing"] == "Sales"
    assert issues[0]["incoming"] == "Revenue Operations"
    assert issues[0]["existing_source"]["source_row"] == 2
    assert issues[0]["incoming_source"]["source_row"] == 3


def test_same_value_from_higher_precedence_source_does_not_hide_later_conflict(tmp_path) -> None:
    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'precedence-hidden-conflict.db'}")):
        with SessionLocal() as db:
            rows = [
                {
                    "data": {"employee_id": "E2004", "department": "Engineering"},
                    "provenance": {
                        "employee_id": _source("employee_payroll.csv", "worker_id", 2),
                        "department": _source("employee_payroll.csv", "dept_name", 2),
                    },
                    "issues": [],
                },
                {
                    "data": {"employee_id": "E2004", "department": "Engineering"},
                    "provenance": {
                        "employee_id": _source("employees_master.csv", "Emp No", 5),
                        "department": _source("employees_master.csv", "Department", 5),
                    },
                    "issues": [],
                },
                {
                    "data": {"employee_id": "E2004", "department": "Finance"},
                    "provenance": {
                        "employee_id": _source("employees_master.csv", "Emp No", 6),
                        "department": _source("employees_master.csv", "Department", 6),
                    },
                    "issues": [],
                },
            ]

            merged = CanonicalizationService(db)._merge_rows("migration-id", rows)

    issues = merged["E2004"]["issues"]
    assert issues[0]["type"] == "SOURCE_VALUE_CONFLICT"
    assert issues[0]["field"] == "department"
    assert issues[0]["existing"] == "Engineering"
    assert issues[0]["incoming"] == "Finance"
    assert issues[0]["existing_source"]["source_file"] == "employees_master.csv"
    assert issues[0]["incoming_source"]["source_file"] == "employees_master.csv"


def test_two_source_columns_for_same_target_create_review_issue() -> None:
    data: dict[str, object] = {}
    provenance: dict[str, dict[str, object]] = {}
    issues: list[dict[str, object]] = []

    _assign_mapped_value(
        data,
        provenance,
        issues,
        "department",
        "Product",
        _source("employees_master.xlsx", "department", 2),
    )
    _assign_mapped_value(
        data,
        provenance,
        issues,
        "department",
        "People Ops",
        _source("employees_master.xlsx", "dept_name", 2),
    )

    assert data["department"] == "Product"
    assert issues == [
        {
            "type": "SOURCE_VALUE_CONFLICT",
            "field": "department",
            "existing": "Product",
            "incoming": "People Ops",
            "existing_source": _source("employees_master.xlsx", "department", 2),
            "incoming_source": _source("employees_master.xlsx", "dept_name", 2),
            "reason": "Two source columns in the same row mapped to the same target field with different values.",
        }
    ]


def _token(client: TestClient) -> str:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "consultant", "password": "demo-password"},
    )
    return login.json()["access_token"]


def _upload_three_files(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/migrations",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            (
                "files",
                (
                    "employees_master.csv",
                    (
                        "Emp No,Employee Name,Start Date,Department\n"
                        "E001,Asha Rao,2022-04-01,Engineering\n"
                        "E002,Rohan Mehta,2021-05-04,Product\n"
                        "E003,Maya Iyer,2023-02-20,Design\n"
                        "E004,Dev Kapoor,2020-01-15,Engineering\n"
                        "E005,Naina Shah,,Sales\n"
                        "E-FAIL-503,Retry Target,2019-08-19,Operations\n"
                    ).encode(),
                    "text/csv",
                ),
            ),
            (
                "files",
                (
                    "employee_contacts.csv",
                    (
                        "employee_code,full_name,mail_id\n"
                        "E001,Asha Rao,ASHA@EXAMPLE.COM\n"
                        "E002,Rohan Mehta,rohan@example.com\n"
                        "E003,Maya Iyer,maya@example.com\n"
                        "E004,Dev Kapoor,dev@example.com\n"
                        "E005,Naina Shah,naina@example.com\n"
                        "E-FAIL-503,Retry Target,retry@example.com\n"
                        "E-FAIL-503,Retry Target,retry@example.com\n"
                    ).encode(),
                    "text/csv",
                ),
            ),
            (
                "files",
                (
                    "employee_payroll.csv",
                    (
                        "worker_id,dept_name,annual_ctc,currency,pay_frequency\n"
                        "E001,Engineering,1000000,INR,ANNUAL\n"
                        "E002,Product,1200000,INR,ANNUAL\n"
                        "E003,Design,1100000,INR,ANNUAL\n"
                        "E004,Finance,1300000,INR,ANNUAL\n"
                        "E-FAIL-503,Operations,99999999,INR,ANNUAL\n"
                    ).encode(),
                    "text/csv",
                ),
            ),
        ],
    )
    assert response.status_code == 201
    return response.json()["migration_id"]


def _source(file_name: str, column: str, row: int) -> dict[str, object]:
    return {
        "source_file": file_name,
        "source_column": column,
        "source_row": row,
        "sheet_name": "employees_master",
    }
