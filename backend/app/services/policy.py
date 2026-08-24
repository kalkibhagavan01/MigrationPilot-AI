from dataclasses import dataclass
from typing import Any

from app.core.constants import FIELD_POLICIES
from app.core.enums import DataClassification, Severity, UserRole
from app.models.user import User
from app.services.masking import mask_sensitive_payload


ROLE_RANK: dict[UserRole, int] = {
    UserRole.IMPLEMENTATION_CONSULTANT: 1,
    UserRole.SENIOR_IMPLEMENTATION_CONSULTANT: 2,
    UserRole.HR_DATA_STEWARD: 3,
    UserRole.COMPENSATION_MANAGER: 3,
    UserRole.PAYROLL_MANAGER: 3,
    UserRole.SYSTEM_ADMIN: 4,
}


@dataclass(frozen=True)
class EscalationPolicy:
    classification: DataClassification
    required_role: UserRole
    severity: Severity
    blocking: bool


class PolicyService:
    def classify_issue(self, issue: dict[str, Any]) -> EscalationPolicy:
        field = str(issue.get("field") or "")
        issue_type = str(issue.get("type") or "")
        reason = str(issue.get("reason") or "")
        field_policy = FIELD_POLICIES.get(field)

        if issue_type == "NUMERIC_OUTLIER" and field in {"annual_salary", "hike_percentage"}:
            return EscalationPolicy(
                classification=DataClassification.CONFIDENTIAL_COMPENSATION,
                required_role=UserRole.COMPENSATION_MANAGER,
                severity=Severity.HIGH,
                blocking=True,
            )

        if "annual_salary" in reason or "hike_percentage" in reason:
            return EscalationPolicy(
                classification=DataClassification.CONFIDENTIAL_COMPENSATION,
                required_role=UserRole.COMPENSATION_MANAGER,
                severity=Severity.HIGH,
                blocking=True,
            )

        if field_policy:
            return EscalationPolicy(
                classification=field_policy["classification"],
                required_role=field_policy["required_role"],
                severity=Severity.MEDIUM,
                blocking=True,
            )

        if issue_type in {"VALIDATION_FAILED", "MISSING_REQUIRED_TARGET_FIELD"}:
            return EscalationPolicy(
                classification=DataClassification.INTERNAL,
                required_role=UserRole.IMPLEMENTATION_CONSULTANT,
                severity=Severity.HIGH,
                blocking=True,
            )

        return EscalationPolicy(
            classification=DataClassification.INTERNAL,
            required_role=UserRole.IMPLEMENTATION_CONSULTANT,
            severity=Severity.MEDIUM,
            blocking=True,
        )

    def can_view_raw(self, user: User, required_role: UserRole) -> bool:
        return user.role == required_role or user.role == UserRole.SYSTEM_ADMIN

    def can_resolve(self, user: User, required_role: UserRole) -> bool:
        if user.role == UserRole.SYSTEM_ADMIN:
            return True
        return user.role == required_role

    def can_see_queue_item(self, user: User, required_role: UserRole) -> bool:
        return self.can_resolve(user, required_role) or ROLE_RANK[user.role] >= ROLE_RANK[required_role]


def mask_sensitive_context(context: dict[str, Any]) -> dict[str, Any]:
    return mask_sensitive_payload(json_safe_copy(context))


def json_safe_copy(context: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, dict):
            copied[key] = dict(value)
        elif isinstance(value, list):
            copied[key] = list(value)
        else:
            copied[key] = value
    return copied
