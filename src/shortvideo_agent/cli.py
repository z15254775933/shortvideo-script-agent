"""CLI for input checks, model probes, and individual business tools."""

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from . import __version__
from .agent import Agent, render_markdown
from .comparison import run_comparison
from .evaluation import evaluate_manifest
from .config import ConfigError, PROJECT_ROOT, Settings
from .contracts import BRIEF, SCHEMAS, SCRIPT, ValidationError, missing_fields
from .io_utils import json_text, read_json, redact, write_json
from .materials import load_assets
from .models import DeepSeekClient, ModelError, OfflineMockClient
from .mock import mock_client
from .tools import ToolRegistry


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Short-video script agent: input, model, and business-tool commands")
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Validate a brief and load local assets; no model call")
    inspect.add_argument("--input", type=Path, required=True)
    inspect.add_argument("--materials", type=Path, default=PROJECT_ROOT / "data/materials.json")
    inspect.add_argument("--rules", type=Path, default=PROJECT_ROOT / "data/brand_rules.json")
    inspect.add_argument("--output", type=Path)
    probe = commands.add_parser("check-model", help="One small real request, or an explicitly scripted mock")
    probe.add_argument("--mode", choices=("mock", "real"), default="mock")
    probe.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    probe.add_argument("--output", type=Path)
    schema = commands.add_parser("schema", help="Export a version-1 JSON Schema contract")
    schema.add_argument("name", choices=tuple(SCHEMAS))
    schema.add_argument("--output", type=Path)
    tool = commands.add_parser("tool", help="Execute one business tool; no agent loop or model call")
    tool_commands = tool.add_subparsers(dest="tool_command", required=True)
    for name in ("search", "estimate", "check"):
        command = tool_commands.add_parser(name)
        command.add_argument("--input", type=Path, required=True, help="Brief that fixes product and target duration")
        command.add_argument("--materials", type=Path, default=PROJECT_ROOT / "data/materials.json")
        command.add_argument("--rules", type=Path, default=PROJECT_ROOT / "data/brand_rules.json")
        command.add_argument("--simulate-failure", action="store_true", help="Explicitly inject one labelled test failure")
        command.add_argument("--output", type=Path)
        if name == "search":
            command.add_argument("--query", required=True)
            command.add_argument("--limit", type=int, default=5)
        else:
            command.add_argument("--script", type=Path, required=True)
    run = commands.add_parser("run", help="Run the bounded agent and save result, trace, journal, and editable script")
    run.set_defaults(output=None)
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--mode", choices=("real", "mock"), default="mock")
    run.add_argument("--mock-scenario", choices=("normal", "repair"), default="normal")
    run.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    run.add_argument("--materials", type=Path, default=PROJECT_ROOT / "data/materials.json")
    run.add_argument("--rules", type=Path, default=PROJECT_ROOT / "data/brand_rules.json")
    run.add_argument("--initial-script", type=Path, help="Optional editable draft; its provided origin is recorded")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--max-tool-calls", type=int)
    run.add_argument("--fail-once", choices=("search_materials", "estimate_duration", "check_rules"))
    run.add_argument("--output-dir", type=Path, help="New directory only; defaults to examples/runs/<unique-id>")
    compare = commands.add_parser("compare-retrieval", help="Two real next-decision probes after one shared saved prefix")
    compare.set_defaults(output=None)
    compare.add_argument("--source-run", type=Path, required=True)
    compare.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    compare.add_argument("--materials", type=Path, default=PROJECT_ROOT / "data/materials.json")
    compare.add_argument("--rules", type=Path, default=PROJECT_ROOT / "data/brand_rules.json")
    compare.add_argument("--output-dir", type=Path)
    evaluate = commands.add_parser("evaluate", help="Offline audit of the saved acceptance cases; no API or credentials")
    evaluate.add_argument("--cases", type=Path, default=PROJECT_ROOT / "data/evaluation_cases.json")
    evaluate.add_argument("--output", type=Path)
    return result


def inspect_input(args: argparse.Namespace) -> tuple[dict, int]:
    brief = read_json(args.input, BRIEF)
    materials, rules = load_assets(args.materials, args.rules)
    missing = missing_fields(brief)
    product_id = brief.get("product_id")
    if product_id and product_id != rules["product_id"]:
        raise ValidationError("Brand rules do not belong to the requested product_id")
    settings = Settings.load()
    result = {
        "schema_version": 1, "kind": "input_inspection",
        "inspection_status": "needs_input" if missing else "ready",
        "not_a_script_generation_result": True, "brief": brief,
        "missing_fields": missing,
        "assets": {
            "materials_synthetic": materials["synthetic"], "rules_synthetic": rules["synthetic"],
            "material_count": len(materials["materials"]),
            "fact_count": sum(len(item["facts"]) for item in materials["materials"]),
            "material_ids": [item["material_id"] for item in materials["materials"]],
            "rule_count": len(rules["rules"]),
        },
        "limits": {"max_steps": settings.max_steps, "max_tool_calls": settings.max_tool_calls},
    }
    return result, 2 if missing else 0


def check_model(args: argparse.Namespace) -> tuple[dict, int]:
    if args.mode == "real":
        client = DeepSeekClient(Settings.load(args.env_file, require_key=True))
    else:
        # Mock must work without an API key, network access, or local .env.
        client = OfflineMockClient()
    reply = client.complete([{"role": "user", "content": "Reply with exactly OK."}], max_tokens=16)
    passed = reply.content is not None and reply.content.strip() == "OK" and not reply.tool_calls
    result = {
        "schema_version": 1, "kind": "model_connection_check",
        "timestamp": datetime.now(timezone.utc).isoformat(), "mode": args.mode,
        "diagnostic_status": "passed" if passed else "failed",
        "evidence_scope": "authentication_and_text_only" if args.mode == "real" else "flow_only",
        "scripted": args.mode == "mock", "not_an_agent_acceptance_result": True,
        **asdict(reply),
    }
    return result, 0 if passed else 3


def run_tool(args: argparse.Namespace) -> tuple[dict, int]:
    brief = read_json(args.input, BRIEF)
    materials, rules = load_assets(args.materials, args.rules)
    name = {"search": "search_materials", "estimate": "estimate_duration", "check": "check_rules"}[args.tool_command]
    registry = ToolRegistry(materials, rules, brief, failures={name: 1} if args.simulate_failure else None)
    arguments = {"query": args.query, "limit": args.limit} if args.tool_command == "search" else {
        "script": read_json(args.script, SCRIPT)}
    result = registry.call(name, arguments)
    if result["status"] == "error":
        return result, 2 if result["error"]["code"] in ("invalid_arguments", "invalid_context") else 3
    return result, 0 if result["result"].get("passed", True) else 2


def run_agent(args: argparse.Namespace) -> tuple[dict, int]:
    brief = read_json(args.input, BRIEF)
    materials, rules = load_assets(args.materials, args.rules)
    initial = read_json(args.initial_script, SCRIPT) if args.initial_script else None
    if args.mode == "real":
        if args.mock_scenario != "normal":
            raise ValidationError("--mock-scenario only applies to mock runs")
        settings = Settings.load(args.env_file, require_key=True)
    else:
        settings = Settings("", "https://api.deepseek.com", "offline-scripted")
        client = mock_client(args.mock_scenario)
    for field, value in (("max_steps", args.max_steps), ("max_tool_calls", args.max_tool_calls)):
        if value is not None:
            if value < 1:
                raise ValidationError("Execution limits must be positive")
            settings = replace(settings, **{field: value})
    if args.mode == "real":
        client = DeepSeekClient(settings)
    registry = ToolRegistry(materials, rules, brief, failures={args.fail_once: 1} if args.fail_once else None)
    output_dir = args.output_dir or PROJECT_ROOT / "examples/runs" / uuid4().hex
    output_dir.mkdir(parents=True, exist_ok=False)

    def journal(event):
        with (output_dir / "events.jsonl").open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(redact(event), ensure_ascii=False, allow_nan=False) + "\n")

    agent = Agent(client, settings, registry, mode=args.mode, initial_script=initial, on_event=journal,
                  metadata={"input_file": str(args.input), "materials_file": str(args.materials),
                            "rules_file": str(args.rules), "initial_script_file": str(args.initial_script) if args.initial_script else None,
                            "mock_scenario": args.mock_scenario if args.mode == "mock" else None})
    try:
        result, trace = agent.run()
    except KeyboardInterrupt:
        result, trace = agent._result("incomplete", "用户中断运行")
    write_json(output_dir / "result.json", result)
    write_json(output_dir / "trace.json", trace)
    with (output_dir / "script.md").open("x", encoding="utf-8", newline="\n") as file:
        file.write(render_markdown(result))
    return {"run_id": result["run_id"], "mode": result["mode"], "status": result["status"],
            "reason": result["reason"], "requests_for_input": result["requests_for_input"],
            "output_dir": str(output_dir.resolve()), "model_calls": trace["model_calls"],
            "tool_calls": trace["tool_calls"]}, {"success": 0, "needs_input": 2}.get(result["status"], 3)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.output and args.output.exists():
            raise FileExistsError
        if args.command == "inspect":
            result, code = inspect_input(args)
        elif args.command == "check-model":
            result, code = check_model(args)
        elif args.command == "tool":
            result, code = run_tool(args)
        elif args.command == "run":
            result, code = run_agent(args)
        elif args.command == "compare-retrieval":
            settings = Settings.load(args.env_file, require_key=True)
            materials, rules = load_assets(args.materials, args.rules)
            destination = args.output_dir or PROJECT_ROOT / "examples/comparisons" / uuid4().hex
            result, code = run_comparison(DeepSeekClient(settings), settings, args.source_run, materials, rules, destination)
        elif args.command == "evaluate":
            result = evaluate_manifest(args.cases)
            code = 0 if result["passed"] == result["total"] else 2
        else:
            result = {"$schema": "https://json-schema.org/draft/2020-12/schema", **SCHEMAS[args.name]}
            code = 0
        if args.output:
            write_json(args.output, result)
        print(json_text(result))
        return code
    except ValidationError as error:
        print(json_text({"kind": "error", "status": "invalid_input", "reason": str(error)}))
        return 2
    except (ConfigError, ModelError) as error:
        print(json_text({"kind": "error", "status": "incomplete", "reason": str(error)}))
        return 3
    except OSError as error:
        print(json_text({"kind": "error", "status": "incomplete", "reason":
            f"File operation failed ({type(error).__name__}); check paths and use a new output filename"}))
        return 4
