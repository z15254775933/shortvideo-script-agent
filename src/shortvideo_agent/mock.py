"""Scripted offline fixtures. They do not demonstrate model decisions."""

import copy
import json

from .config import PROJECT_ROOT
from .contracts import SCRIPT
from .io_utils import read_json
from .models import ModelError, ModelReply


def tool_reply(name: str, arguments: dict, call_id: str = "fixture_call") -> ModelReply:
    return ModelReply("offline-scripted", None, [{"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments, ensure_ascii=False),
    }}], "tool_calls", {})


class ScriptedAgentClient:
    def __init__(self, replies: list[ModelReply]):
        self.replies = copy.deepcopy(replies)

    def complete(self, messages: list[dict], *, tools=None, max_tokens=4096) -> ModelReply:
        if not self.replies:
            raise ModelError("离线固定脚本已耗尽；这不是模型决策失败或真实模型结果")
        return self.replies.pop(0)


def mock_client(scenario: str) -> ScriptedAgentClient:
    short = read_json(PROJECT_ROOT / "examples/tool_inputs/within_budget.json", SCRIPT)
    plan = [("search_materials", {"query": "字幕", "reason_summary": "固定 Mock 步骤：检索字幕素材"})]
    if scenario == "repair":
        long = read_json(PROJECT_ROOT / "examples/tool_inputs/overlong.json", SCRIPT)
        plan.append(("estimate_duration", {"script": long, "reason_summary": "固定 Mock 步骤：检查长稿"}))
    plan.extend([
        ("estimate_duration", {"script": short, "reason_summary": "固定 Mock 步骤：检查预设短稿"}),
        ("check_rules", {"script": short, "reason_summary": "固定 Mock 步骤：核对事实和品牌规则"}),
        ("finish_task", {"status": "success", "reason": "固定 Mock 流程结束，仅证明程序执行流程",
                         "requests_for_input": [], "risks": ["这些动作和脚本全部预设，不能证明真实模型决策效果。"]}),
    ])
    return ScriptedAgentClient([tool_reply(name, arguments, f"fixture_call_{index}")
                                for index, (name, arguments) in enumerate(plan, 1)])
