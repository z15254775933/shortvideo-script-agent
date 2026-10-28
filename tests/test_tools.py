"""Deterministic business-tool tests, not evidence of model decision quality."""

import copy
import json
import unittest
from unittest.mock import patch
from decimal import Decimal

from src.shortvideo_agent.config import PROJECT_ROOT
from src.shortvideo_agent.contracts import BRIEF, SCRIPT, ValidationError
from src.shortvideo_agent.io_utils import read_json
from src.shortvideo_agent.materials import load_assets
from src.shortvideo_agent.tools import (
    TimingPolicy, ToolRegistry, check_rules, estimate_duration,
    normalize, script_identity, search_materials, tool_definitions,
)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.materials, self.rules = load_assets(PROJECT_ROOT / "data/materials.json", PROJECT_ROOT / "data/brand_rules.json")
        self.brief = read_json(PROJECT_ROOT / "examples/inputs/normal.json", BRIEF)
        self.script = read_json(PROJECT_ROOT / "examples/tool_inputs/within_budget.json", SCRIPT)

    def check(self, script=None, materials=None, rules=None):
        return check_rules(self.script if script is None else script,
                           self.materials if materials is None else materials,
                           self.rules if rules is None else rules, product_id="demo_editor")

    def codes(self, result):
        return {issue["code"] for issue in result["details"]["issues"]}

    def one_scene(self, voiceover="", subtitle="", min_visual=0, pause=0):
        script = copy.deepcopy(self.script)
        script["scenes"] = [script["scenes"][0]]
        script["scenes"][0].update(voiceover=voiceover, subtitle=subtitle,
                                   min_visual_seconds=min_visual, pause_seconds=pause)
        return script

    def test_search_hit_empty_and_stable_tie_breaking(self):
        result = search_materials(self.materials, "字幕", product_id="demo_editor")
        self.assertEqual([item["material_id"] for item in result["matches"]], ["P01", "P02"])
        self.assertEqual(result["matches"][0]["facts"][0]["statement"], "支持字幕")
        self.assertEqual(search_materials(self.materials, "降噪")["matches"], [])

    def test_search_limits_results_and_does_not_mutate_sources(self):
        result = search_materials(self.materials, "字幕", limit=1)
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["returned_count"], 1)
        self.assertTrue(result["truncated"])
        result["matches"][0]["facts"][0]["statement"] = "changed"
        self.assertEqual(self.materials["materials"][0]["facts"][0]["statement"], "支持字幕")

    def test_search_rejects_bad_query_or_limit(self):
        for query in ("", "   ", "!!!", "%"):
            with self.assertRaises(ValidationError):
                search_materials(self.materials, query)
        for limit in (0, 11, True):
            with self.assertRaises(ValidationError):
                search_materials(self.materials, "字幕", limit=limit)

    def test_search_product_filter_prevents_cross_product_results(self):
        self.materials["materials"][0]["product_id"] = "another_product"
        result = search_materials(self.materials, "字幕", product_id="demo_editor")
        self.assertEqual([item["material_id"] for item in result["matches"]], ["P02"])

    def test_known_chinese_speech_and_punctuation_estimate(self):
        result = estimate_duration(self.one_scene("支持字幕。"), 30)
        self.assertEqual(result["details"]["estimated_total_seconds"], 1.2)

    def test_english_words_digits_and_chinese_have_defined_rates(self):
        script = self.one_scene("Hello world 字幕 12")
        result = estimate_duration(script, 30)
        self.assertEqual(result["details"]["estimated_total_seconds"], 1.8)

    def test_simultaneous_subtitle_and_speech_use_maximum_not_sum(self):
        result = estimate_duration(self.one_scene("支持字幕", "支持字幕"), 30)
        self.assertEqual(result["details"]["estimated_total_seconds"], 1.0)

    def test_subtitle_only_and_visual_pause_budgets(self):
        self.assertEqual(estimate_duration(self.one_scene(subtitle="支持字幕"), 30)["details"]["estimated_total_seconds"], 0.8)
        result = estimate_duration(self.one_scene("支持字幕", min_visual=5, pause=0.5), 30)
        self.assertEqual(result["details"]["estimated_total_seconds"], 5.5)

    def test_time_boundary_uses_upward_rounding_and_decimal_sum(self):
        script = self.one_scene(pause=0.21)
        self.assertFalse(estimate_duration(script, 0.29)["passed"])
        self.assertTrue(estimate_duration(script, 0.3)["passed"])
        result = estimate_duration(self.script, 30)
        durations = [Decimal(str(scene["estimated_duration_seconds"])) for scene in result["details"]["scenes"]]
        self.assertEqual(sum(durations), Decimal(str(result["details"]["estimated_total_seconds"])))

    def test_time_recomputes_instead_of_trusting_reported_numbers(self):
        script = read_json(PROJECT_ROOT / "examples/tool_inputs/overlong.json", SCRIPT)
        before = copy.deepcopy(script)
        result = estimate_duration(script, 30)
        self.assertFalse(result["passed"])
        self.assertEqual(result["details"]["estimated_total_seconds"], 43.5)
        self.assertEqual(script, before)

    def test_target_change_alters_check_result_without_changing_script(self):
        self.assertTrue(estimate_duration(self.script, 30)["passed"])
        self.assertFalse(estimate_duration(self.script, 10)["passed"])

    def test_invalid_timing_targets_and_rates_fail(self):
        for value in (True, 0, -1, float("nan")):
            with self.assertRaises(ValidationError):
                estimate_duration(self.script, value)
        with self.assertRaises(ValidationError):
            TimingPolicy(spoken_characters_per_second=0)

    def test_check_accepts_supported_script_and_reports_each_citation(self):
        result = self.check()
        self.assertTrue(result["passed"], result)
        self.assertEqual({item["fact_id"] for item in result["details"]["verified_citations"]}, {"P01-F01", "P02-F01"})

    def test_valid_ids_cannot_support_an_expanded_claim(self):
        scene = self.script["scenes"][0]
        scene["citations"][0]["claim"] = "支持字幕，效率提升80%"
        scene["voiceover"] = "支持字幕，效率提升80%"
        result = self.check()
        self.assertFalse(result["passed"])
        self.assertIn("claim_not_supported", self.codes(result))

    def test_extra_claim_outside_valid_citation_is_blocked_even_without_brand_rules(self):
        script = read_json(PROJECT_ROOT / "examples/tool_inputs/unsupported_claim.json", SCRIPT)
        result = self.check(script, rules={**self.rules, "rules": []})
        self.assertFalse(result["passed"])
        self.assertIn("unverified_text", self.codes(result))

    def test_fullwidth_percent_and_spacing_do_not_bypass_brand_rule(self):
        script = read_json(PROJECT_ROOT / "examples/tool_inputs/unsupported_claim.json", SCRIPT)
        result = self.check(script)
        self.assertIn("forbidden_phrase", self.codes(result))
        self.assertTrue(any(issue.get("rule_id") == "B01" for issue in result["details"]["issues"]))

    def test_unknown_source_wrong_pair_and_cross_product_are_rejected(self):
        for material_id, fact_id in (("missing", "P01-F01"), ("P01", "P02-F01")):
            with self.subTest(source=material_id):
                script = copy.deepcopy(self.script)
                script["scenes"][0]["citations"][0].update(material_id=material_id, fact_id=fact_id)
                self.assertIn("unknown_source", self.codes(self.check(script)))
        self.materials["materials"][0]["product_id"] = "other"
        self.assertIn("wrong_product_source", self.codes(self.check()))

    def test_unused_and_missing_citations_are_rejected(self):
        scene = self.script["scenes"][0]
        scene.update(voiceover="先看功能", subtitle="")
        self.assertIn("unused_citation", self.codes(self.check()))
        scene.update(voiceover="支持字幕", citations=[])
        self.assertIn("unverified_text", self.codes(self.check()))

    def test_qualifiers_cannot_be_removed(self):
        self.materials["materials"][0]["facts"][0]["qualifiers"] = ["仅限桌面版"]
        self.assertIn("claim_not_supported", self.codes(self.check()))
        scene = self.script["scenes"][0]
        scene["citations"][0]["claim"] = "支持字幕；仅限桌面版"
        scene.update(voiceover="支持字幕；仅限桌面版", subtitle="支持字幕；仅限桌面版")
        self.assertTrue(self.check()["passed"])

    def test_decimals_and_percent_units_are_not_cosmetic_punctuation(self):
        self.assertNotEqual(normalize("1.5倍"), normalize("15倍"))
        self.assertNotEqual(normalize("1/2"), normalize("12"))
        self.assertNotEqual(normalize("80%"), normalize("80"))
        self.materials["materials"][0]["facts"][0]["statement"] = "支持1.5倍播放"
        scene = self.script["scenes"][0]
        scene.update(voiceover="支持15倍播放", subtitle="支持15倍播放")
        scene["citations"][0]["claim"] = "支持15倍播放"
        self.assertIn("claim_not_supported", self.codes(self.check()))

    def test_unverified_assertions_in_title_visual_or_subtitle_are_rejected(self):
        for field in ("title", "visual", "subtitle"):
            script = copy.deepcopy(self.script)
            if field == "title":
                script[field] = "一键自动识别声音并生成字幕"
            else:
                script["scenes"][0][field] = "一键自动识别声音并生成字幕"
            self.assertIn("unverified_text", self.codes(self.check(script)))

    def test_duplicate_scenes_empty_text_and_no_product_evidence_are_rejected(self):
        self.script["scenes"][1]["scene_id"] = "S01"
        self.assertIn("duplicate_scene_id", self.codes(self.check()))
        self.script["scenes"][0].update(voiceover="", subtitle="")
        self.assertIn("missing_scene_text", self.codes(self.check()))
        for scene in self.script["scenes"]:
            scene["citations"] = []
        self.assertIn("missing_product_evidence", self.codes(self.check()))

    def test_required_disclaimer_is_checked_in_displayed_or_spoken_copy(self):
        rules = {**self.rules, "rules": [{"rule_id": "D01", "kind": "required_disclaimer",
                  "value": "演示画面仅供参考", "description": "需要演示声明"}]}
        self.assertIn("missing_disclaimer", self.codes(self.check(rules=rules)))
        self.script["scenes"][-1]["subtitle"] += "演示画面仅供参考。"
        self.assertTrue(self.check(rules=rules)["passed"])

    def test_safe_unlisted_rephrasing_is_conservatively_rejected(self):
        self.script["scenes"][0]["voiceover"] += "让我们开始吧。"
        result = self.check()
        self.assertFalse(result["passed"])
        self.assertIn("unverified_text", self.codes(result))

    def test_identity_binds_revision_text_citation_and_visual_budget(self):
        initial = script_identity(self.script)
        for field, value in (("voiceover", "changed"), ("min_visual_seconds", 6), ("pause_seconds", 1)):
            script = copy.deepcopy(self.script)
            script["scenes"][0][field] = value
            self.assertNotEqual(initial, script_identity(script))
        script = copy.deepcopy(self.script)
        script["revision"] += 1
        self.assertNotEqual(initial, script_identity(script))

    def test_identity_ignores_tool_computed_estimates_and_check_types_agree(self):
        initial = script_identity(self.script)
        self.script["estimated_total_seconds"] = 999
        self.script["scenes"][0]["estimated_duration_seconds"] = 998
        self.assertEqual(initial, script_identity(self.script))
        timing, rules = estimate_duration(self.script, 30), self.check()
        self.assertEqual(timing["script_sha256"], rules["script_sha256"])

    def test_registry_binds_product_target_and_does_not_let_model_change_rates(self):
        registry = ToolRegistry(self.materials, self.rules, {**self.brief, "target_duration_seconds": 10})
        result = registry.call("estimate_duration", {"script": self.script})
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["result"]["passed"])
        self.assertEqual(registry.call("estimate_duration", {"script": self.script, "target_duration_seconds": 100})["error"]["code"], "invalid_arguments")

    def test_registry_errors_are_distinct_from_failed_business_checks(self):
        registry = ToolRegistry(self.materials, self.rules, self.brief)
        self.assertEqual(registry.call("unknown", {})["error"]["code"], "unknown_tool")
        self.assertEqual(registry.call("search_materials", {"query": "字幕", "limit": 99})["error"]["code"], "invalid_arguments")
        missing = ToolRegistry(self.materials, self.rules, {"schema_version": 1})
        self.assertEqual(missing.call("estimate_duration", {"script": self.script})["error"]["code"], "invalid_context")

    def test_explicit_fault_injection_does_not_retry_automatically(self):
        registry = ToolRegistry(self.materials, self.rules, self.brief, failures={"search_materials": 1})
        first = registry.call("search_materials", {"query": "字幕"})
        self.assertEqual(first["status"], "error")
        self.assertTrue(first["simulated_failure"])
        second = registry.call("search_materials", {"query": "字幕"})
        self.assertEqual(second["status"], "ok")

    def test_unexpected_tool_exception_is_reported_without_leaking_details(self):
        registry = ToolRegistry(self.materials, self.rules, self.brief)
        fake_secret = "sk-" + "z" * 32
        with patch("src.shortvideo_agent.tools.estimate_duration", side_effect=RuntimeError(fake_secret)):
            result = registry.call("estimate_duration", {"script": self.script})
        self.assertEqual(result["error"]["code"], "tool_execution_error")
        self.assertFalse(result["error"]["retryable"])
        self.assertNotIn(fake_secret, json.dumps(result))

    def test_tool_definitions_are_serializable_and_detached_from_internal_schemas(self):
        definitions = tool_definitions()
        self.assertEqual({item["function"]["name"] for item in definitions},
                         {"search_materials", "estimate_duration", "check_rules"})
        json.dumps(definitions, ensure_ascii=False)
        definitions[0]["function"]["parameters"]["properties"].clear()
        self.assertIn("query", tool_definitions()[0]["function"]["parameters"]["properties"])


if __name__ == "__main__":
    unittest.main()
