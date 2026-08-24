from datetime import datetime
from decimal import Decimal, InvalidOperation
import re


EXPLICIT_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y")


def clean_value(target_field: str, raw_value: object) -> tuple[object | None, list[dict[str, object]]]:
    value = "" if raw_value is None else str(raw_value).strip()
    issues: list[dict[str, object]] = []
    if value == "":
        return None, issues

    if target_field == "email":
        return value.lower(), issues

    if target_field in {"phone", "employee_id", "manager_id", "bank_account_number", "tax_identifier"}:
        return value, issues

    if target_field in {"date_of_birth", "joining_date"}:
        parsed, issue = _parse_date(value)
        if issue:
            issues.append({"type": issue, "field": target_field, "value": value})
        return parsed, issues

    if target_field == "employment_type":
        normalized = value.upper().replace(" ", "_")
        enum_map = {
            "PERMANENT": "PERMANENT",
            "FULL_TIME": "PERMANENT",
            "CONTRACT": "CONTRACT",
            "CONTRACTOR": "CONTRACT",
            "INTERN": "INTERN",
            "TEMPORARY": "TEMPORARY",
            "TEMP": "TEMPORARY",
        }
        return enum_map.get(normalized, normalized), issues

    if target_field in {"annual_salary", "hike_percentage"}:
        try:
            return Decimal(value.replace(",", "")), issues
        except InvalidOperation:
            issues.append({"type": "INVALID_NUMBER", "field": target_field, "value": value})
            return None, issues

    if target_field == "currency":
        return value.upper(), issues

    if target_field == "pay_frequency":
        return value.upper(), issues

    return value, issues


def _parse_date(value: str) -> tuple[str | None, str | None]:
    if _is_ambiguous_slash_date(value):
        return None, "AMBIGUOUS_DATE_FORMAT"

    for date_format in EXPLICIT_DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).date().isoformat(), None
        except ValueError:
            continue

    return None, "INVALID_DATE_FORMAT"


def _is_ambiguous_slash_date(value: str) -> bool:
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value)
    if not match:
        return False
    day = int(match.group(1))
    month = int(match.group(2))
    return day <= 12 and month <= 12
