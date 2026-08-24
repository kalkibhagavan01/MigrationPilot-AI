from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.employee import EmployeeTarget


def valid_employee(**overrides: object) -> dict[str, object]:
    employee: dict[str, object] = {
        "employee_id": "E001",
        "full_name": "Asha Rao",
        "email": "asha.rao@example.com",
        "joining_date": date(2022, 4, 1),
    }
    employee.update(overrides)
    return employee


def test_valid_employee_schema_accepts_required_fields() -> None:
    employee = EmployeeTarget.model_validate(valid_employee())

    assert employee.employee_id == "E001"


def test_joining_date_cannot_be_before_date_of_birth() -> None:
    with pytest.raises(ValidationError, match="joining_date cannot be before date_of_birth"):
        EmployeeTarget.model_validate(
            valid_employee(date_of_birth=date(2000, 1, 1), joining_date=date(1999, 1, 1))
        )


def test_salary_requires_currency_and_pay_frequency() -> None:
    with pytest.raises(ValidationError, match="annual_salary requires currency"):
        EmployeeTarget.model_validate(valid_employee(annual_salary=Decimal("1200000")))

    with pytest.raises(ValidationError, match="annual_salary requires pay_frequency"):
        EmployeeTarget.model_validate(
            valid_employee(annual_salary=Decimal("1200000"), currency="INR")
        )


def test_manager_cannot_equal_employee_id() -> None:
    with pytest.raises(ValidationError, match="manager_id cannot equal employee_id"):
        EmployeeTarget.model_validate(valid_employee(manager_id="E001"))
