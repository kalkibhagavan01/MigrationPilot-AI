from typing import Any


SENSITIVE_FIELD_NAMES = frozenset(
    {
        "salary",
        "annual_salary",
        "hike",
        "hike_percentage",
        "dob",
        "date_of_birth",
        "phone",
        "mobile",
        "mobile_number",
        "bank",
        "bank_account",
        "bank_account_number",
        "account_number",
        "tax",
        "tax_identifier",
        "ssn",
        "pan",
        "aadhaar",
    }
)


def mask_sensitive_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: _mask_value(value) if _is_sensitive_key(key) and value is not None else mask_sensitive_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [mask_sensitive_payload(item) for item in payload]
    return payload


def masked_field_names(payload: dict[str, Any]) -> list[str]:
    return sorted({key for key in payload if _is_sensitive_key(key) and payload[key] is not None})


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").strip()
    if normalized in SENSITIVE_FIELD_NAMES:
        return True
    return any(token in normalized for token in ("salary", "dob", "phone", "mobile", "bank", "tax", "ssn", "pan", "aadhaar"))


def _mask_value(value: Any) -> str:
    text = str(value)
    if text == "":
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]
