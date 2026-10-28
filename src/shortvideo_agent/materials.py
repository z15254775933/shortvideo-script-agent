"""Load assets and reject ambiguous material, fact, or rule identifiers."""

from pathlib import Path

from .contracts import MATERIALS, RULES, ValidationError, validate
from .io_utils import read_json


def load_assets(materials_path: Path, rules_path: Path) -> tuple[dict, dict]:
    materials = read_json(materials_path, MATERIALS)
    rules = read_json(rules_path, RULES)
    validate_assets(materials, rules)
    return materials, rules


def validate_assets(materials: dict, rules: dict) -> None:
    validate(materials, MATERIALS)
    validate(rules, RULES)
    seen_materials, seen_facts, seen_rules = set(), set(), set()
    for material in materials["materials"]:
        if material["material_id"] in seen_materials:
            raise ValidationError("Duplicate material_id")
        seen_materials.add(material["material_id"])
        for fact in material["facts"]:
            if fact["fact_id"] in seen_facts:
                raise ValidationError("Duplicate fact_id")
            seen_facts.add(fact["fact_id"])
    for rule in rules["rules"]:
        if rule["rule_id"] in seen_rules:
            raise ValidationError("Duplicate rule_id")
        seen_rules.add(rule["rule_id"])
