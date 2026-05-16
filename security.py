from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


JWT_SECRET = os.getenv("JWT_SECRET", "dev-change-me")
JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", "86400"))


class TokenError(ValueError):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}")


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def create_access_token(*, user_id: str, username: str, role: str) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + JWT_TTL_SECONDS,
    }
    signing_input = f"{_b64encode(_json_dumps(header))}.{_b64encode(_json_dumps(payload))}"
    signature = hmac.new(JWT_SECRET.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
    except ValueError as exc:
        raise TokenError("Invalid token format.") from exc

    signing_input = f"{encoded_header}.{encoded_payload}"
    expected = hmac.new(JWT_SECRET.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    actual = _b64decode(encoded_signature)
    if not hmac.compare_digest(expected, actual):
        raise TokenError("Invalid token signature.")

    try:
        payload = json.loads(_b64decode(encoded_payload))
    except json.JSONDecodeError as exc:
        raise TokenError("Invalid token payload.") from exc

    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("Token expired.")
    return payload
