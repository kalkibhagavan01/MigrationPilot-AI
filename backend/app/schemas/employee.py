from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class EmployeeTarget(BaseModel):
    employee_id: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = None

    date_of_birth: date | None = None
    joining_date: date

    department: str | None = None
    location: str | None = None
    employment_type: Literal["PERMANENT", "CONTRACT", "INTERN", "TEMPORARY"] | None = None

    manager_id: str | None = None

    annual_salary: Decimal | None = Field(default=None, ge=0)
    hike_percentage: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    pay_frequency: Literal["MONTHLY", "ANNUAL", "WEEKLY"] | None = None

    bank_account_number: str | None = None
    tax_identifier: str | None = None

    @model_validator(mode="after")
    def validate_cross_field_rules(self) -> "EmployeeTarget":
        if self.date_of_birth and self.joining_date < self.date_of_birth:
            raise ValueError("joining_date cannot be before date_of_birth")

        if self.annual_salary is not None and not self.currency:
            raise ValueError("annual_salary requires currency")

        if self.annual_salary is not None and not self.pay_frequency:
            raise ValueError("annual_salary requires pay_frequency")

        if self.manager_id and self.manager_id == self.employee_id:
            raise ValueError("manager_id cannot equal employee_id")

        return self
