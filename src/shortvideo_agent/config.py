"""Local .env loading; process environment takes precedence."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    pass


def env_values(path: Path) -> dict[str, str]:
    result = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not key.strip().replace("_", "").isalnum():
                raise ConfigError("Invalid .env line; expected KEY=VALUE")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[key.strip()] = value
    result.update(os.environ)
    return result


def positive_int(values: dict, key: str, default: int) -> int:
    try:
        value = int(values.get(key, default))
    except (ValueError, TypeError) as error:
        raise ConfigError(f"{key} must be a positive integer") from error
    if value < 1:
        raise ConfigError(f"{key} must be a positive integer")
    return value


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout_seconds: int = 30
    max_steps: int = 10
    max_tool_calls: int = 16
    max_output_tokens: int = 4096

    @classmethod
    def load(cls, env_file: Path = PROJECT_ROOT / ".env", *, require_key: bool = False):
        values = env_values(env_file)
        api_key = values.get("DEEPSEEK_API_KEY", "").strip()
        if require_key and (not api_key or api_key == "your_deepseek_api_key_here"):
            raise ConfigError("Set DEEPSEEK_API_KEY in local .env or the process environment")
        base_url = values.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        try:
            url = urlsplit(base_url)
            allowed = (url.scheme == "https" and url.hostname == "api.deepseek.com"
                       and url.port in (None, 443) and url.path in ("", "/v1")
                       and not url.username and not url.password and not url.query and not url.fragment)
        except ValueError as error:
            raise ConfigError("Invalid DeepSeek base URL") from error
        if not allowed:
            raise ConfigError("This adapter only sends credentials to the official DeepSeek HTTPS host")
        model = values.get("DEEPSEEK_MODEL", "deepseek-flash").strip()
        if not model:
            raise ConfigError("DEEPSEEK_MODEL must not be blank")
        return cls(api_key, base_url, model,
                   positive_int(values, "MODEL_TIMEOUT_SECONDS", 30),
                   positive_int(values, "AGENT_MAX_STEPS", 10),
                   positive_int(values, "AGENT_MAX_TOOL_CALLS", 16),
                   positive_int(values, "AGENT_MAX_OUTPUT_TOKENS", 4096))
