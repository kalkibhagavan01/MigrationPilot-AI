import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import AppError


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2_sha256$200000${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = password_hash.split("$", maxsplit=3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(candidate.hex(), digest)


def create_access_token(
    subject: str,
    secret: str,
    expires_delta: timedelta,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": subject,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + expires_delta).timestamp()),
    }
    signing_input = f"{_b64_json(header)}.{_b64_json(payload)}"
    signature = _b64_bytes(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


def decode_access_token(token: str, secret: str, now: datetime | None = None) -> dict[str, Any]:
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise AppError("TOKEN_INVALID", "Token is invalid.", 401) from exc

    signing_input = f"{header_segment}.{payload_segment}"
    expected_signature = _b64_bytes(
        hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected_signature, signature_segment):
        raise AppError("TOKEN_INVALID", "Token is invalid.", 401)

    payload = _decode_json(payload_segment)
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int):
        raise AppError("TOKEN_INVALID", "Token is invalid.", 401)

    current_time = now or datetime.now(UTC)
    if current_time.timestamp() >= expires_at:
        raise AppError("TOKEN_EXPIRED", "Token has expired.", 401)

    return payload


def _b64_json(value: dict[str, Any]) -> str:
    return _b64_bytes(json.dumps(value, separators=(",", ":")).encode())


def _b64_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode_json(segment: str) -> dict[str, Any]:
    padding = "=" * (-len(segment) % 4)
    try:
        decoded = base64.urlsafe_b64decode(segment + padding)
        value = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise AppError("TOKEN_INVALID", "Token is invalid.", 401) from exc

    if not isinstance(value, dict):
        raise AppError("TOKEN_INVALID", "Token is invalid.", 401)

    return value
