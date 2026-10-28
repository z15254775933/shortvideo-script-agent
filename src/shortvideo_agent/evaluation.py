"""Offline acceptance audit of actual saved runs; never calls a model."""

import hashlib
import json
from decimal import Decimal
from datetime import datetime
from pathlib import Path, PureWindowsPath

from .agent import render_markdown, utc_now
from .comparison import comparison_outcome
from .config import PROJECT_ROOT
from .contracts import RESULT, TRACE, ValidationError, array, obj
from .io_utils import read_json
from .materials import load_assets
from .tools import check_rules, estimate_duration, normalize, script_identity
from .grounding import check_creative_rules, parse_review, request_fingerprint

CASE_MANIFEST = obj({
    "schema_version": {"type": "integer", "const": 1},
    "cases": array(obj({
        "id": {"type": "string", "minLength": 1}, "description": {"type": "string", "minLength": 1},
        "kind": {"type": "string", "enum": ["normal", "missing", "no_materials", "tool_failure",
                                                 "time_repair", "rule_repair", "limits", "comparison",
                                                 "creative", "creative_repair"]},
        "paths": array({"type": "string", "minLength": 1}, 1),
    }), 1),
})


class AuditError(ValueError):
    pass


def require(condition, message: str) -> None:
    if not condition:
        raise AuditError(message)


def repo_path(recorded: str, *, metadata: bool = False) -> Path:
    """Resolve portable repo paths, including old Windows source-path metadata."""
    normalized = recorded.replace("\\", "/")
    if metadata and not normalized.startswith(("data/", "examples/")):
        for marker in ("data/", "examples/"):
            token = "/" + marker
            if token in normalized:
                normalized = marker + normalized.split(token, 1)[1]
                break
    require(not Path(normalized).is_absolute() and not PureWindowsPath(normalized).drive,
            "Evidence paths must be repository-relative")
    if metadata:
        require(normalized.startswith(("data/", "examples/")), "Source metadata must refer to repository data or examples")
    target = (PROJECT_ROOT / normalized).resolve()
    require(target.is_relative_to(PROJECT_ROOT.resolve()), "Evidence paths must stay inside this repository")
    return target


def verify_loaded(result: dict, trace: dict, journal: list, materials: dict, rules: dict) -> None:
    require(result["run_id"] == trace["run_id"], "Result and trace run IDs differ")
    require(result["mode"] == trace["mode"], "Run modes differ")
    require(result["brief"] == trace["input"], "Saved input was changed")
    require(result["status"] == trace["final_status"], "Final states differ")
    require(result["reason"] == trace["end_reason"], "End reasons differ")
    require(journal == trace["events"], "Journal and final trace differ")
    require([event["step"] for event in journal] == list(range(1, len(journal) + 1)), "Event sequence is invalid")
    require(journal[-1]["kind"] == "final", "Missing final event")
    require(trace["model_calls"] == sum(event["kind"] == "model_request" for event in journal), "Model count mismatch")
    require(trace["tool_calls"] == sum(event["kind"] == "tool_call" for event in journal), "Tool count mismatch")
    require(trace["model_calls"] <= trace["limits"]["max_steps"], "Model limit exceeded")
    require(trace["tool_calls"] <= trace["limits"]["max_tool_calls"], "Tool limit exceeded")
    creative = trace["metadata"].get("writing_mode") == "creative"
    require((result.get("writing_mode") == "creative") == creative, "Writing mode mismatch")
    if creative:
        metadata = trace["metadata"]
        records = metadata["review_records"]
        require(metadata["review_model_calls"] == len(records) <= metadata["max_review_calls"], "Review count or limit mismatch")
        require(metadata["total_model_calls"] == trace["model_calls"] + len(records), "Total request count mismatch")
        require([record["sequence"] for record in records] == list(range(1, len(records) + 1)), "Review sequence mismatch")
        for record in records:
            require(record["request_sha256"] == request_fingerprint(record["input"]), "Review request fingerprint mismatch")
            if record["status"] == "ok":
                require(record["finish_reason"] == "stop" and not record["tool_calls"], "Incomplete review response")
                require(parse_review(record["content"], record["input"]) == record["review"], "Review response was changed")
        for event in journal:
            saved = event["observation"].get("result", {}).get("details", {}).get("semantic_review")
            if event["kind"] == "tool_result" and saved and saved.get("sequence"):
                require(1 <= saved["sequence"] <= len(records), "Review call record missing")
                actual = records[saved["sequence"] - 1]
                require({k: v for k, v in saved.items() if k != "cache_hit"} ==
                        {k: v for k, v in actual.items() if k != "cache_hit"}, "Tool result differs from actual review response")
    if result["script"]:
        drafts = [event["observation"]["script"] for event in journal if event["kind"] == "draft_registered"]
        require(bool(drafts) and script_identity(drafts[-1]) == script_identity(result["script"]), "Final script differs from registered draft")
    if result["status"] != "success":
        return
    require(result["script"] is not None, "Success has no script")
    require(len(result["checks"]) == 2 and {check["tool"] for check in result["checks"]} == {"estimate_duration", "check_rules"}, "Missing final checks")
    script = result["script"]
    computed = {
        "estimate_duration": estimate_duration(script, result["brief"]["target_duration_seconds"]),
    }
    saved_rules = next(check for check in result["checks"] if check["tool"] == "check_rules")
    if creative:
        record = saved_rules["details"].get("semantic_review")
        require(record is not None and record.get("status") == "ok", "Success has no complete independent review")
        try:
            computed["check_rules"] = check_creative_rules(script, materials, rules, result["brief"], saved_record=record)
        except ValueError:
            raise AuditError("Stored creative review does not validate this script under current checks") from None
    else:
        computed["check_rules"] = check_rules(script, materials, rules, product_id=result["brief"].get("product_id"))
    for check in result["checks"]:
        require(check["passed"] and check == computed[check["tool"]], "Saved check differs from recomputed result")
        require(any(event["kind"] == "tool_result" and event["observation"].get("result") == check for event in journal), "Check has no actual tool-result event")
    total = sum(Decimal(str(scene["estimated_duration_seconds"])) for scene in script["scenes"])
    require(total == Decimal(str(script["estimated_total_seconds"])), "Scene and total durations differ")
    require(float(total) == computed["estimate_duration"]["details"]["estimated_total_seconds"], "Final duration differs from recomputation")
    retrieved = {(material["material_id"], fact["fact_id"])
                 for event in journal if event["kind"] == "tool_result" and event["action"] == "search_materials"
                 and event["observation"].get("status") == "ok"
                 for material in event["observation"]["result"]["matches"] for fact in material["facts"]}
    require(all((citation["material_id"], citation["fact_id"]) in retrieved
                for scene in script["scenes"] for citation in scene["citations"]), "Citation was not retrieved")


def audit_bundle(directory: Path) -> dict:
    result = read_json(directory / "result.json", RESULT)
    trace = read_json(directory / "trace.json", TRACE)
    journal = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    materials, rules = load_assets(repo_path(trace["metadata"]["materials_file"], metadata=True),
                                  repo_path(trace["metadata"]["rules_file"], metadata=True))
    verify_loaded(result, trace, journal, materials, rules)
    require((directory / "script.md").is_file(), "Editable Markdown output missing")
    require((directory / "script.md").read_text(encoding="utf-8") == render_markdown(result), "Markdown differs from the structured result")
    return {"result": result, "trace": trace, "materials": materials, "rules": rules}


def results_for(trace: dict, tool: str) -> list[dict]:
    return [event for event in trace["events"] if event["kind"] == "tool_result" and event["action"] == tool]


def changed_after_observation(trace: dict, failed: dict) -> dict:
    drafts = [event for event in trace["events"] if event["kind"] == "draft_registered" and event["step"] > failed["step"]]
    require(bool(drafts), "No revised draft after failed observation")
    require(any(event["kind"] == "model_response" and failed["step"] < event["step"] < drafts[0]["step"]
                for event in trace["events"]), "Draft change has no intervening model decision")
    return drafts[0]


def audit_comparison(directory: Path, source_run: Path) -> dict:
    documents = {name: json.loads((directory / filename).read_text(encoding="utf-8")) for name, filename in (
        ("shared", "shared-prefix.json"), ("available", "available.next-decision.json"),
        ("empty", "empty.next-decision.json"), ("summary", "summary.json"))}
    shared, full, empty, summary = (documents[name] for name in ("shared", "available", "empty", "summary"))
    fingerprint = hashlib.sha256(json.dumps(shared["messages"], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    require(all(document["common_prefix_sha256"] == fingerprint for document in documents.values()), "Shared prefix fingerprints differ")
    require(shared["replayed_actual_prior_response"] is True, "Probe provenance missing")
    source = read_json(source_run / "trace.json", TRACE)
    require(source["mode"] == "real" and source["run_id"] == shared["source_run_id"], "Probe did not reuse the stated actual run")
    response = next((event for event in source["events"] if event["step"] == shared["source_response_event"]), None)
    require(response is not None and response["kind"] == "model_response", "Source response event missing")
    require(shared["messages"][-1]["tool_calls"] == response["observation"]["tool_calls"], "Replayed tools were not selected by the source model")
    materials, rules = load_assets(repo_path(source["metadata"]["materials_file"], metadata=True),
                                  repo_path(source["metadata"]["rules_file"], metadata=True))
    require(len(full["tool_observations"]) == len(empty["tool_observations"]) == len(response["observation"]["tool_calls"]), "Probe observation counts differ")
    from .tools import ToolRegistry
    for record, dataset in ((full, materials), (empty, {**materials, "materials": []})):
        registry = ToolRegistry(dataset, rules, source["input"])
        for observation, call in zip(record["tool_observations"], response["observation"]["tool_calls"]):
            expected_arguments = json.loads(call["function"]["arguments"])
            expected_arguments.pop("reason_summary", None)
            require(observation["tool_call_id"] == call["id"] and observation["arguments"] == expected_arguments, "Probe query provenance differs")
            require(observation["observation"] == registry.call("search_materials", expected_arguments), "Probe tool observation was not reproducible")
    require(full["mode"] == empty["mode"] == summary["mode"] == "real", "Comparison is not real-model evidence")
    require(full["actual_new_model_calls"] == empty["actual_new_model_calls"] == 1, "Probe count invalid")
    require(full["does_not_execute_next_actions"] and empty["does_not_execute_next_actions"], "Probe was mislabelled as a full run")
    require([item["arguments"] for item in full["tool_observations"]] == [item["arguments"] for item in empty["tool_observations"]], "Queries changed between branches")
    require(all(item["observation"]["result"]["matched_count"] > 0 for item in full["tool_observations"]), "Available branch has no evidence")
    require(all(item["observation"]["result"]["matched_count"] == 0 for item in empty["tool_observations"]), "Empty branch is not empty")
    require(comparison_outcome(full["reply"], empty["reply"]) and summary["comparison_status"] == "observed", "Expected next-action change not observed")
    return {"available_tools": [call["function"]["name"] for call in full["reply"]["tool_calls"]],
            "empty_tools": [call["function"]["name"] for call in empty["reply"]["tool_calls"]],
            "new_model_calls": 2, "full_task_results": False, "common_prefix_sha256": fingerprint}


def audit_case(case: dict) -> dict:
    paths = [repo_path(path) for path in case["paths"]]
    if case["kind"] == "comparison":
        require(len(paths) == 2, "Comparison requires its actual source run")
        return audit_comparison(paths[0], paths[1])
    bundles = [audit_bundle(path) for path in paths]
    require(all(bundle["result"]["mode"] == "real" for bundle in bundles), "Acceptance case must use real-model evidence")
    bundle = bundles[0]
    result, trace = bundle["result"], bundle["trace"]
    metrics = {"status": result["status"], "model_calls": trace["model_calls"], "tool_calls": trace["tool_calls"]}
    kind = case["kind"]
    if kind in ("normal", "tool_failure", "time_repair", "rule_repair", "creative", "creative_repair"):
        require(result["status"] == "success", "Case did not produce a checked script")
        metrics["estimated_seconds"] = result["script"]["estimated_total_seconds"]
    if kind in ("creative", "creative_repair"):
        require(result.get("writing_mode") == "creative", "Case did not use independent creative review")
        metrics.update(review_model_calls=trace["metadata"]["review_model_calls"],
                       total_model_calls=trace["metadata"]["total_model_calls"])
        metrics["elapsed_seconds"] = round((datetime.fromisoformat(trace["events"][-1]["timestamp"])
                                             - datetime.fromisoformat(trace["started_at"])).total_seconds(), 3)
        author_usage = [event["observation"].get("usage", {}) for event in trace["events"] if event["kind"] == "model_response"]
        review_usage = [record.get("usage", {}) for record in trace["metadata"]["review_records"]]
        metrics["tokens"] = {name: {key: sum(usage.get(key, 0) for usage in rows)
                                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
                             for name, rows in (("author", author_usage), ("review", review_usage))}
        require(not check_rules(result["script"], bundle["materials"], bundle["rules"])["passed"],
                "Creative example did not exercise text outside the strict policy")
        if kind == "creative_repair":
            failed = next((event for event in results_for(trace, "check_rules")
                           if event["observation"].get("status") == "ok"
                           and any(issue["code"] == "semantic_unsupported" for issue in
                                   event["observation"]["result"]["details"]["issues"])), None)
            require(failed is not None, "No actual semantic failure observation")
            changed_after_observation(trace, failed)
            metrics["semantic_failure_event"] = failed["step"]
    elif kind == "missing":
        require(result["status"] == "needs_input" and result["requests_for_input"] and result["script"] is None, "Missing information was not requested")
        require("target_duration_seconds" not in result["brief"], "Missing target was invented")
    elif kind == "no_materials":
        searches = results_for(trace, "search_materials")
        require(searches and all(event["observation"]["result"]["matches"] == [] for event in searches), "No-material path is not empty")
        require(result["status"] == "needs_input" and result["requests_for_input"] and result["script"] is None, "No-material path fabricated a final script")
        metrics["empty_retrievals"] = len(searches)
    elif kind == "tool_failure":
        failures = [event for event in results_for(trace, "search_materials") if event["observation"].get("simulated_failure")]
        require(len(failures) == 1, "Expected one labelled tool fault")
        failed = failures[0]
        decisions = [event for event in trace["events"] if event["kind"] == "model_response" and event["step"] > failed["step"]]
        require(decisions, "No model response after tool error")
        retry = next((event for event in trace["events"] if event["kind"] == "tool_call" and event["action"] == "search_materials"
                      and event["step"] > decisions[0]["step"]), None)
        require(retry is not None, "No model-selected retry after observing the fault")
        metrics.update(fault_event=failed["step"], retry_event=retry["step"])
    elif kind == "time_repair":
        timings = results_for(trace, "estimate_duration")
        failed = next((event for event in timings if event["observation"].get("status") == "ok" and not event["observation"]["result"]["passed"]), None)
        require(failed is not None, "No actual overtime observation")
        draft = changed_after_observation(trace, failed)
        require(any(event["step"] > draft["step"] and event["observation"]["result"]["passed"] for event in timings), "No successful re-estimate")
        metrics.update(before_seconds=failed["observation"]["result"]["details"]["estimated_total_seconds"], changed_draft_event=draft["step"])
    elif kind == "rule_repair":
        failed = next((event for event in results_for(trace, "check_rules") if event["observation"].get("status") == "ok"
                       and not event["observation"]["result"]["passed"] and {"unverified_text", "forbidden_phrase"}.issubset(
                           {issue["code"] for issue in event["observation"]["result"]["details"]["issues"]})), None)
        require(failed is not None, "No actual unsupported-claim and brand-rule observation")
        changed_after_observation(trace, failed)
        require(len(bundle["materials"]["materials"]) == 1 and bundle["materials"]["materials"][0]["material_id"] == "P01", "Case is not caption-only")
        require(normalize("效率提升80%") not in normalize(json.dumps(result["script"], ensure_ascii=False)), "Unsupported claim remained in final script")
        metrics.update(rule_failure_event=failed["step"], source_ids=["P01"])
    elif kind == "limits":
        require(len(bundles) == 2, "Verify both model and tool limits")
        for item in bundles:
            require(item["result"]["status"] == "incomplete" and "上限" in item["result"]["reason"], "Limit did not produce explicit unfinished state")
        require(bundles[0]["trace"]["limits"]["max_steps"] == 1 and bundles[0]["trace"]["model_calls"] == 1, "Model limit case invalid")
        require(bundles[1]["trace"]["limits"]["max_tool_calls"] == 1 and bundles[1]["trace"]["tool_calls"] == 1, "Tool limit case invalid")
        metrics["verified_limits"] = ["model_steps", "tool_calls"]
    return metrics


def evaluate_manifest(path: Path) -> dict:
    manifest = read_json(path, CASE_MANIFEST)
    ids = [case["id"] for case in manifest["cases"]]
    if len(set(ids)) != len(ids):
        raise ValidationError("Evaluation IDs must be unique")
    rows = []
    for case in manifest["cases"]:
        row = {"id": case["id"], "description": case["description"], "evidence": case["paths"]}
        try:
            row.update(passed=True, metrics=audit_case(case))
        except (ValueError, OSError, KeyError, IndexError, TypeError) as error:
            row.update(passed=False, error=str(error) if isinstance(error, AuditError) else f"Evidence audit failed ({type(error).__name__})")
        rows.append(row)
    return {"schema_version": 1, "kind": "acceptance_evaluation", "timestamp": utc_now(),
            "evidence_scope": "offline_audit_of_actual_saved_model_runs", "new_model_calls": 0,
            "total": len(rows), "passed": sum(row["passed"] for row in rows), "cases": rows,
            "limitations": ["验收针对已保存样本，不代表模型统计成功率或通用语义能力。创作模式重放已存审核，不重新裁决自然语言真值。",
                            "C01 是两个受控单步决策，不是两次完整 Agent 任务。"]}
