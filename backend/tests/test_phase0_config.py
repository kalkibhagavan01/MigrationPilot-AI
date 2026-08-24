from app.core.constants import FIELD_POLICIES, SOURCE_PRECEDENCE
from app.core.enums import DataClassification, UserRole


def test_sensitive_field_policy_routes_salary_to_compensation_manager() -> None:
    policy = FIELD_POLICIES["annual_salary"]

    assert policy["classification"] == DataClassification.CONFIDENTIAL_COMPENSATION
    assert policy["required_role"] == UserRole.COMPENSATION_MANAGER


def test_source_precedence_prefers_master_for_department_conflicts() -> None:
    assert SOURCE_PRECEDENCE["department"][0] == "employees_master.csv"


def test_contact_source_owns_email() -> None:
    assert SOURCE_PRECEDENCE["email"] == ["employee_contacts.xlsx"]
