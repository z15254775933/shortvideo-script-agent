"""Strict JSON loading and credential-safe diagnostic output."""

import json
import re
from pathlib import Path
from typing import Any

from .contracts import ValidationError, validate

_SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_SENSITIVE_KEYS = {"api_key", "deepseek_api_key", "authorization", "access_token"}


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.lower() in _SENSITIVE_KEYS else redact(child)
                for key, child in value.items()}
    if isinstance(value, list):
        return [redact(child) for child in value]
    return value


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON contains a duplicate field")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValidationError("JSON must not contain NaN or infinity")


def read_json(path: Path, schema: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"),
                           object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValidationError("Input is not valid UTF-8 JSON") from error
    validate(value, schema)
    return value


def json_text(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, indent=2, allow_nan=False)


def write_json(path: Path, value: Any) -> None:
    """Create a new output; never silently overwrite a source or old run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json_text(value) + "\n")
