"""Versioned JSON contracts, shared by validation and schema export.

The validator implements only the keywords used below, not all of JSON Schema.
Business constraints (grounding, duration, final-version checks) belong to tools.
"""

import math
from typing import Any


class ValidationError(ValueError):
    pass


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def array(items: dict, minimum: int = 0) -> dict:
    return {"type": "array", "items": items, "minItems": minimum}


TEXT = {"type": "string", "minLength": 1}
STRING = {"type": "string"}
NUMBER = {"type": "number", "minimum": 0}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
VERSION = {"type": "integer", "const": 1}
FREE_OBJECT = {"type": "object"}
STATUS = {"type": "string", "enum": ["success", "needs_input", "incomplete", "invalid_input"]}
MODE = {"type": "string", "enum": ["real", "mock"]}
CREATIVE_FIELDS = ("topic", "audience", "platform", "target_duration_seconds", "style")

BRIEF = obj({
    "schema_version": VERSION,
    "topic": {"type": ["string", "null"]},
    "audience": {"type": ["string", "null"]},
    "platform": {"type": ["string", "null"]},
    "target_duration_seconds": {"type": ["number", "null"], "exclusiveMinimum": 0},
    "style": {"type": ["string", "null"]},
    "product_id": TEXT,
}, required=["schema_version"])

FACT = obj({"fact_id": TEXT, "statement": TEXT, "qualifiers": array(TEXT)})
MATERIAL = obj({
    "material_id": TEXT, "product_id": TEXT, "title": TEXT,
    "tags": array(TEXT), "facts": array(FACT, 1),
})
MATERIALS = obj({
    "schema_version": VERSION, "synthetic": {"type": "boolean"},
    "description": TEXT, "materials": array(MATERIAL),
})
RULE = obj({
    "rule_id": TEXT,
    "kind": {"type": "string", "enum": ["forbidden_phrase", "required_disclaimer"]},
    "value": TEXT, "description": TEXT,
})
RULES = obj({
    "schema_version": VERSION, "synthetic": {"type": "boolean"},
    "product_id": TEXT, "rules": array(RULE),
})
CITATION = obj({"material_id": TEXT, "fact_id": TEXT, "claim": TEXT})
SCENE = obj({
    "scene_id": TEXT, "visual": TEXT, "voiceover": STRING, "subtitle": STRING,
    "pause_seconds": NUMBER, "min_visual_seconds": NUMBER,
    "estimated_duration_seconds": {"type": ["number", "null"], "minimum": 0},
    "citations": array(CITATION),
})
SCRIPT = obj({
    "schema_version": VERSION, "revision": {"type": "integer", "minimum": 1},
    "title": TEXT, "scenes": array(SCENE, 1),
    "estimated_total_seconds": {"type": ["number", "null"], "minimum": 0},
})
CHECK = obj({
    "tool": {"type": "string", "enum": ["estimate_duration", "check_rules"]},
    "script_revision": {"type": "integer", "minimum": 1}, "script_sha256": TEXT,
    "passed": {"type": "boolean"}, "summary": TEXT, "details": FREE_OBJECT,
})
RESULT = obj({
    "schema_version": VERSION, "run_id": TEXT, "mode": MODE, "status": STATUS,
    "reason": TEXT, "brief": BRIEF, "script": {**SCRIPT, "type": ["object", "null"]},
    "checks": array(CHECK), "risks": array(TEXT), "requests_for_input": array(TEXT),
})
EVENT = obj({
    "step": {"type": "integer", "minimum": 1}, "timestamp": TEXT,
    "kind": {"type": "string", "enum": [
        "input_validation", "model_request", "model_response", "draft_registered", "tool_call", "tool_result", "final",
    ]},
    "action": TEXT, "reason_summary": STRING,
    "arguments": FREE_OBJECT, "observation": FREE_OBJECT,
})
TRACE = obj({
    "schema_version": VERSION, "run_id": TEXT, "mode": MODE, "model": TEXT,
    "started_at": TEXT, "input": BRIEF,
    "metadata": FREE_OBJECT,
    "limits": obj({"max_steps": {"type": "integer", "minimum": 1},
                   "max_tool_calls": {"type": "integer", "minimum": 1}}),
    "events": array(EVENT), "final_status": STATUS, "end_reason": TEXT,
    "model_calls": {"type": "integer", "minimum": 0},
    "tool_calls": {"type": "integer", "minimum": 0},
})
SCHEMAS = {"brief": BRIEF, "materials": MATERIALS, "rules": RULES,
           "script": SCRIPT, "result": RESULT, "trace": TRACE}


def validate(value: Any, schema: dict, path: str = "$") -> None:
    """Validate structure without echoing potentially sensitive field values."""
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    matches = {
        "null": value is None, "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str), "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }
    if types and not any(matches[t] for t in types):
        raise ValidationError(f"{path}: expected {' or '.join(types)}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{path}: unsupported choice")
    if "const" in schema and value != schema["const"]:
        raise ValidationError(f"{path}: unsupported schema version")
    if value is None:
        return
    if matches["number"]:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValidationError(f"{path}: number must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise ValidationError(f"{path}: number below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValidationError(f"{path}: number above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise ValidationError(f"{path}: number must exceed minimum")
    if isinstance(value, str) and "minLength" in schema:
        if len(value.strip()) < schema["minLength"]:
            raise ValidationError(f"{path}: text must not be blank")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                raise ValidationError(f"{path}.{name}: required field missing")
        properties = schema.get("properties", {})
        for name, child in value.items():
            if name in properties:
                validate(child, properties[name], f"{path}.{name}")
            elif schema.get("additionalProperties") is False:
                raise ValidationError(f"{path}: unknown field")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValidationError(f"{path}: too few items")
        for index, child in enumerate(value):
            validate(child, schema.get("items", {}), f"{path}[{index}]")


def missing_fields(brief: dict) -> list[str]:
    return [name for name in CREATIVE_FIELDS
            if brief.get(name) is None or
            (isinstance(brief.get(name), str) and not brief[name].strip())]
