"""DeepSeek Chat Completions adapter and a clearly labelled offline probe.

No business decisions, retries, or fake production traces live in this layer.
Thinking is disabled; internal reasoning is neither returned nor logged.
"""

import json
from dataclasses import dataclass
from typing import Callable
from urllib import error, request

from .config import Settings


class ModelError(RuntimeError):
    pass


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class ModelReply:
    model: str
    content: str | None
    tool_calls: list[dict]
    finish_reason: str
    usage: dict

    def assistant_message(self) -> dict:
        result = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        return result


class DeepSeekClient:
    def __init__(self, settings: Settings, open_request: Callable | None = None):
        self.settings = settings
        self._open = open_request or request.build_opener(_NoRedirect()).open

    def complete(self, messages: list[dict], *, tools: list[dict] | None = None,
                 max_tokens: int = 2048) -> ModelReply:
        if not self.settings.api_key:
            raise ModelError("DeepSeek API key is not configured")
        body = {"model": self.settings.model, "messages": messages,
                "max_tokens": max_tokens, "stream": False, "thinking": {"type": "disabled"}}
        if tools:
            body.update(tools=tools, tool_choice="auto")
        api_request = request.Request(
            self.settings.base_url + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.settings.api_key,
                     "Content-Type": "application/json"}, method="POST",
        )
        try:
            with self._open(api_request, timeout=self.settings.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            # Never print raw response bodies, request objects, or headers.
            status_code = exc.code
            exc.close()
            raise ModelError(f"DeepSeek returned HTTP {status_code}; no automatic retry") from None
        except (error.URLError, TimeoutError, OSError):
            raise ModelError("DeepSeek network or timeout error; no automatic retry") from None
        except (ValueError, UnicodeDecodeError):
            raise ModelError("DeepSeek returned invalid JSON") from None
        return self._parse(payload)

    @staticmethod
    def _parse(payload: dict) -> ModelReply:
        try:
            if not isinstance(payload, dict):
                raise ValueError
            choices = payload["choices"]
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError
            choice = choices[0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise ValueError
            content = message.get("content")
            calls = message.get("tool_calls")
            calls = [] if calls is None else calls
            finish = choice["finish_reason"]
            if message["role"] != "assistant" or not isinstance(calls, list):
                raise ValueError
            if content is not None and not isinstance(content, str):
                raise ValueError
            if finish not in ("stop", "tool_calls"):
                raise ModelError("DeepSeek response incomplete or filtered; cannot accept as a final answer")
            clean_calls = []
            for call in calls:
                function = call["function"]
                if (call["type"] != "function" or not isinstance(call["id"], str) or not call["id"]
                        or not isinstance(function["name"], str) or not function["name"]
                        or not isinstance(function["arguments"], str)):
                    raise ValueError
                clean_calls.append({"id": call["id"], "type": "function", "function": {
                    "name": function["name"], "arguments": function["arguments"],
                }})
            if not clean_calls and not content:
                raise ValueError
            if bool(clean_calls) != (finish == "tool_calls"):
                raise ValueError
            model = payload["model"]
            if not isinstance(model, str) or not model:
                raise ValueError
            raw_usage = payload.get("usage") or {}
            if not isinstance(raw_usage, dict):
                raise ValueError
            usage = {key: raw_usage[key] for key in (
                "prompt_tokens", "completion_tokens", "total_tokens") if key in raw_usage}
            if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
                   for value in usage.values()):
                raise ValueError
            return ModelReply(model, content, clean_calls, finish, usage)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelError("DeepSeek returned an unsupported response structure") from None


class OfflineMockClient:
    """A fixed OK response solely for exercising the offline connection command."""

    def complete(self, messages: list[dict], *, tools: list[dict] | None = None,
                 max_tokens: int = 2048) -> ModelReply:
        return ModelReply("offline-mock", "OK", [], "stop", {})
