"""A transparent one-step retrieval intervention, not a full agent run.

Reuse an actual saved model tool selection as a common prefix; rerun its
retrievals against available/empty data, then ask the real model once per branch.
"""

import copy
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from .agent import Agent, agent_tool_definitions, utc_now
from .config import Settings
from .contracts import TRACE, ValidationError
from .io_utils import json_text, read_json, write_json
from .models import ModelError
from .tools import ToolRegistry


def probe_contexts(trace: dict, settings: Settings, materials: dict, rules: dict) -> tuple[dict, dict]:
    if trace["mode"] != "real" or settings.model != trace["model"]:
        raise ValidationError("Use an actual real run made with the same configured model")
    response_event = next((event for event in trace["events"] if event["kind"] == "model_response"
                           and event["observation"].get("tool_calls")), None)
    if response_event is None:
        raise ValidationError("Source run has no model-selected tools")
    response = response_event["observation"]
    if any(call["function"]["name"] != "search_materials" for call in response["tool_calls"]):
        raise ValidationError("Source run must start with a batch of actual retrieval choices")
    initial = next((event["observation"]["script"] for event in trace["events"]
                    if event["kind"] == "draft_registered" and event["observation"]["origin"] == "provided_input"), None)
    limits = replace(settings, max_steps=trace["limits"]["max_steps"], max_tool_calls=trace["limits"]["max_tool_calls"])
    base = Agent(None, limits, ToolRegistry(materials, rules, trace["input"]), mode="real", initial_script=initial)
    messages = copy.deepcopy(base.messages)
    messages.append({"role": "assistant", "content": response["content"], "tool_calls": response["tool_calls"]})
    fingerprint = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    shared = {"schema_version": 1, "kind": "comparison_shared_prefix", "source_run_id": trace["run_id"],
              "source_response_event": response_event["step"], "replayed_actual_prior_response": True,
              "common_prefix_sha256": fingerprint, "messages": messages, "tools": agent_tool_definitions(),
              "scope": "Reconstructed common prefix plus one new model decision per branch; not a complete run."}
    branches = {}
    empty = {**materials, "materials": [], "description": "Controlled empty dataset for a retrieval-result intervention"}
    for name, dataset in (("available", materials), ("empty", empty)):
        registry = ToolRegistry(dataset, rules, trace["input"])
        branch_messages, observations = copy.deepcopy(messages), []
        for call in response["tool_calls"]:
            arguments = json.loads(call["function"]["arguments"])
            arguments.pop("reason_summary", None)
            observation = registry.call("search_materials", arguments)
            if observation["status"] != "ok":
                raise ValidationError("Controlled retrieval failed; cannot compare model decisions")
            observations.append({"tool_call_id": call["id"], "arguments": arguments, "observation": observation})
            branch_messages.append({"role": "tool", "tool_call_id": call["id"], "content": json_text(observation)})
        branches[name] = {"messages": branch_messages, "observations": observations}
    return shared, branches


def selected_actions(reply: dict) -> list[dict]:
    actions = []
    for call in reply.get("tool_calls", []):
        try:
            arguments = json.loads(call["function"]["arguments"])
        except (ValueError, TypeError):
            arguments = None
        actions.append({"tool": call["function"]["name"], "arguments": arguments})
    return actions


def comparison_outcome(available: dict, empty: dict) -> bool:
    generated = any(action["tool"] in ("estimate_duration", "check_rules")
                    and isinstance(action["arguments"], dict) and "script" in action["arguments"]
                    for action in selected_actions(available))
    sought_evidence = any(action["tool"] == "search_materials" or (
        action["tool"] == "finish_task" and isinstance(action["arguments"], dict)
        and action["arguments"].get("status") in ("needs_input", "incomplete"))
        for action in selected_actions(empty))
    return generated and sought_evidence


def run_comparison(client, settings: Settings, source_run: Path, materials: dict, rules: dict,
                   output_dir: Path) -> tuple[dict, int]:
    trace = read_json(source_run / "trace.json", TRACE)
    shared, contexts = probe_contexts(trace, settings, materials, rules)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "shared-prefix.json", shared)
    records = {}
    for branch, context in contexts.items():
        record = {"schema_version": 1, "kind": "controlled_next_decision", "mode": "real",
                  "evidence_scope": "single_step_after_replayed_prefix", "branch": branch,
                  "timestamp": utc_now(), "common_prefix_sha256": shared["common_prefix_sha256"],
                  "changed_variable": "retrieval_results", "actual_new_model_calls": 1,
                  "tool_observations": context["observations"], "does_not_execute_next_actions": True}
        try:
            reply = client.complete(context["messages"], tools=agent_tool_definitions(), max_tokens=settings.max_output_tokens)
            record.update(diagnostic_status="ok", reply=asdict(reply))
        except ModelError as error:
            record.update(diagnostic_status="error", error=str(error))
        records[branch] = record
        write_json(output_dir / f"{branch}.next-decision.json", record)
    error = any(record["diagnostic_status"] != "ok" for record in records.values())
    observed = not error and comparison_outcome(records["available"]["reply"], records["empty"]["reply"])
    summary = {"schema_version": 1, "kind": "retrieval_decision_comparison", "mode": "real",
               "evidence_scope": "two_single_step_decisions_not_full_runs", "actual_new_model_calls": 2,
               "common_prefix_sha256": shared["common_prefix_sha256"],
               "comparison_status": "error" if error else "observed" if observed else "not_observed",
               "available_actions": selected_actions(records["available"].get("reply", {})),
               "empty_actions": selected_actions(records["empty"].get("reply", {})),
               "limitations": ["共享首轮工具选择来自已保存的真实运行；本次仅两个后续决策为新调用。",
                               "这是一组对照样本，不代表统计成功率；未执行新动作或宣告完整任务通过。"]}
    write_json(output_dir / "summary.json", summary)
    return {"comparison_status": summary["comparison_status"], "output_dir": str(output_dir.resolve()),
            "available_tools": [action["tool"] for action in summary["available_actions"]],
            "empty_tools": [action["tool"] for action in summary["empty_actions"]], "actual_new_model_calls": 2}, 3 if error else 0 if observed else 2
