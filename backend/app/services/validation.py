from app.core.enums import ValidationStatus
from app.schemas.employee import EmployeeTarget


class ValidationService:
    def validate(self, data: dict[str, object]) -> tuple[ValidationStatus, list[dict[str, object]]]:
        try:
            EmployeeTarget.model_validate(data)
        except ValueError as exc:
            return ValidationStatus.INVALID, [{"type": "VALIDATION_FAILED", "reason": str(exc)}]

        return ValidationStatus.VALID, []
