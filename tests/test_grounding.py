"""Scripted reviewer tests cover enforcement, not model judgement quality."""

import copy
import json
import unittest
from unittest.mock import patch

from src.shortvideo_agent.agent import Agent, render_markdown
from src.shortvideo_agent.cli import parser, run_agent
from src.shortvideo_agent.config import PROJECT_ROOT, Settings
from src.shortvideo_agent.contracts import BRIEF, SCRIPT, ValidationError
from src.shortvideo_agent.grounding import (
    SemanticReviewer, check_creative_rules, writing_guidance,
)
from src.shortvideo_agent.io_utils import read_json
from src.shortvideo_agent.materials import load_assets
from src.shortvideo_agent.mock import mock_client
from src.shortvideo_agent.models import ModelError, ModelReply
from src.shortvideo_agent.tools import ToolRegistry, check_rules


class FixtureReviewerClient:
    def __init__(self, transform=None, error=None):
        self.transform, self.error, self.calls = transform, error, 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        payload = json.loads(messages[-1]["content"])
        fields = [{"location": field["location"],
                   "verdict": "supported" if field["allowed_fact_ids"] else "non_factual",
                   "fact_ids": field["allowed_fact_ids"], "reason": "预设审核结论，不代表真实模型效果"}
                  for field in payload["fields"]]
        review = {"fields": fields}
        if self.transform:
            self.transform(review)
        return ModelReply("offline-review-fixture", json.dumps(review, ensure_ascii=False), [], "stop", {})


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.materials, self.rules = load_assets(PROJECT_ROOT / "data/materials.json", PROJECT_ROOT / "data/brand_rules.json")
        self.brief = read_json(PROJECT_ROOT / "examples/inputs/normal.json", BRIEF)
        self.script = read_json(PROJECT_ROOT / "examples/tool_inputs/within_budget.json", SCRIPT)

    def check(self, reviewer, script=None):
        return check_creative_rules(self.script if script is None else script,
                                    self.materials, self.rules, self.brief, reviewer)

    def test_free_editorial_text_can_pass_without_weakening_exact_citations(self):
        self.script["title"] = "这句字幕，你想怎么改？"
        self.script["scenes"][0]["visual"] = "演员拿出一张写有旁白的纸卡，镜头缓缓推近。"
        self.assertFalse(check_rules(self.script, self.materials, self.rules)["passed"])
        checked = self.check(SemanticReviewer(FixtureReviewerClient()))
        self.assertTrue(checked["passed"])
        self.assertEqual(checked["details"]["grounding_policy"]["name"], "exact_citations_and_semantic_review_v2")

    def test_bad_id_and_omitted_qualifier_fail_before_any_model_review(self):
        client = FixtureReviewerClient()
        self.script["scenes"][0]["citations"][0]["fact_id"] = "not-provided"
        self.assertFalse(self.check(SemanticReviewer(client))["passed"])
        self.script = read_json(PROJECT_ROOT / "examples/tool_inputs/within_budget.json", SCRIPT)
        self.materials["materials"][0]["facts"][0]["qualifiers"] = ["仅限桌面版"]
        self.assertFalse(self.check(SemanticReviewer(client))["passed"])
        self.assertEqual(client.calls, 0)

    def test_forbidden_numbers_fail_before_model_review(self):
        self.script["scenes"][0]["voiceover"] += "效率提升８０％。"
        client = FixtureReviewerClient()
        checked = self.check(SemanticReviewer(client))
        self.assertFalse(checked["passed"])
        self.assertTrue(any(issue["code"] == "forbidden_phrase" for issue in checked["details"]["issues"]))
        self.assertEqual(client.calls, 0)

    def test_manual_subtitle_editing_cannot_imply_no_reediting_or_rerecording(self):
        for promise in ("不用重剪", "无需重录"):
            script = copy.deepcopy(self.script)
            script["scenes"][0]["voiceover"] += promise
            client = FixtureReviewerClient()
            checked = self.check(SemanticReviewer(client), script)
            self.assertFalse(checked["passed"])
            self.assertEqual(client.calls, 0)
            self.assertTrue(any(issue["code"] == "unsupported_workflow_promise" for issue in checked["details"]["issues"]))

    def test_semantic_rejection_is_a_failed_check_with_location(self):
        def reject(review):
            review["fields"][0].update(verdict="unsupported", reason="标题暗示了素材没有说明的自动识别能力")
        checked = self.check(SemanticReviewer(FixtureReviewerClient(reject)))
        self.assertFalse(checked["passed"])
        self.assertEqual(checked["details"]["issues"][0]["code"], "semantic_unsupported")
        self.assertEqual(checked["details"]["issues"][0]["location"], "title")

    def test_missing_duplicate_or_unknown_field_never_counts_as_reviewed(self):
        transforms = [lambda r: r["fields"].pop(),
                      lambda r: r["fields"].append(copy.deepcopy(r["fields"][0])),
                      lambda r: r["fields"][0].update(location="unknown")]
        for transform in transforms:
            with self.subTest(transform=transform):
                checked = self.check(SemanticReviewer(FixtureReviewerClient(transform)))
                self.assertFalse(checked["passed"])
                self.assertEqual(checked["details"]["issues"][0]["code"], "semantic_review_unavailable")

    def test_review_cannot_invent_sources_or_leave_supported_verdict_without_evidence(self):
        for source_ids in ([], ["fake-fact"]):
            def change(review):
                review["fields"][0].update(verdict="supported", fact_ids=source_ids)
            self.assertFalse(self.check(SemanticReviewer(FixtureReviewerClient(change)))["passed"])

    def test_optional_text_echo_must_match_the_exact_reviewed_field(self):
        good = lambda r: r["fields"][0].update(text=self.script["title"])
        bad = lambda r: r["fields"][0].update(text="another field")
        self.assertTrue(self.check(SemanticReviewer(FixtureReviewerClient(good)))["passed"])
        self.assertFalse(self.check(SemanticReviewer(FixtureReviewerClient(bad)))["passed"])

    def test_network_failure_is_counted_and_never_passed_or_automatically_retried(self):
        client = FixtureReviewerClient(error=ModelError("test failure"))
        reviewer = SemanticReviewer(client, max_calls=1)
        self.assertFalse(self.check(reviewer)["passed"])
        self.assertFalse(self.check(reviewer)["passed"])
        self.assertEqual(client.calls, 1)
        self.assertEqual(reviewer.calls, 1)
        self.assertEqual(reviewer.records[0]["status"], "error")

    def test_identical_review_is_cached_but_draft_change_requires_new_request(self):
        client = FixtureReviewerClient()
        reviewer = SemanticReviewer(client, max_calls=1)
        first, second = self.check(reviewer), self.check(reviewer)
        self.assertTrue(first["passed"] and second["passed"])
        self.assertTrue(second["details"]["semantic_review"]["cache_hit"])
        self.script["title"] = "另一个开场"
        third = self.check(reviewer)
        self.assertFalse(third["passed"])
        self.assertEqual(client.calls, 1)
        self.assertEqual(third["details"]["semantic_review"]["status"], "limit")

    def test_saved_review_replays_offline_and_detects_changed_input_or_response(self):
        original = self.check(SemanticReviewer(FixtureReviewerClient()))
        record = original["details"]["semantic_review"]
        replayed = check_creative_rules(self.script, self.materials, self.rules, self.brief, saved_record=record)
        self.assertEqual(original, replayed)
        for key, value in (("content", '{"fields":[]}'), ("request_sha256", "changed")):
            changed = {**record, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_creative_rules(self.script, self.materials, self.rules, self.brief, saved_record=changed)
        with self.assertRaises(ValidationError):
            check_creative_rules(self.script, self.materials, self.rules, {**self.brief, "style": "changed"}, saved_record=record)

    def test_registry_search_exposes_active_policy_and_platform_guidance(self):
        registry = ToolRegistry(self.materials, self.rules, self.brief, reviewer=SemanticReviewer(FixtureReviewerClient()))
        found = registry.call("search_materials", {"query": "字幕"})["result"]
        self.assertEqual(found["grounding_policy"]["name"], "exact_citations_and_semantic_review_v2")
        self.assertIn("竖屏", found["writing_guidance"]["suggested_structure"])
        self.assertIn("分点", writing_guidance({**self.brief, "platform": "B站"})["suggested_structure"])

    def test_agent_uses_creative_policy_and_counts_author_and_review_calls_separately(self):
        reviewer = SemanticReviewer(FixtureReviewerClient())
        registry = ToolRegistry(self.materials, self.rules, self.brief, reviewer=reviewer)
        agent = Agent(mock_client("normal"), Settings("", "https://api.deepseek.com", "offline-fixture"), registry, mode="mock")
        result, trace = agent.run()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["writing_mode"], "creative")
        self.assertEqual(trace["metadata"]["review_model_calls"], 1)
        self.assertEqual(trace["metadata"]["total_model_calls"], trace["model_calls"] + 1)
        self.assertEqual(len(trace["metadata"]["review_records"]), 1)
        self.assertIn("分镜时间轴", render_markdown(result))
        self.assertIn("0.0—", render_markdown(result))
        self.assertIn("允许自由创作", agent.messages[0]["content"])
        shown = [json.loads(message["content"]) for message in agent.messages if message["role"] == "tool"]
        rule_observation = next(item for item in shown if item.get("tool") == "check_rules")
        self.assertNotIn("semantic_review", rule_observation["result"]["details"])
        self.assertEqual(rule_observation["result"]["details"]["semantic_review_summary"]["reviewed_fields"], 10)
        self.assertIn("content", trace["metadata"]["review_records"][0])

    def test_rejected_semantic_review_cannot_be_finished_as_success(self):
        def reject(review):
            review["fields"][0].update(verdict="unsupported", reason="预设拒绝，用于验证程序边界")
        reviewer = SemanticReviewer(FixtureReviewerClient(reject))
        registry = ToolRegistry(self.materials, self.rules, self.brief, reviewer=reviewer)
        result, trace = Agent(mock_client("normal"), Settings("", "https://api.deepseek.com", "fixture"), registry, mode="mock").run()
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(any(event["observation"].get("error", {}).get("code") == "final_evidence_missing"
                            for event in trace["events"]))

    def test_creative_mode_cannot_be_misrepresented_as_a_network_free_cli_mock(self):
        args = parser().parse_args(["run", "--mode", "mock", "--writing-mode", "creative", "--input", "examples/inputs/normal.json"])
        with patch.object(Settings, "load", side_effect=AssertionError("credentials accessed")), self.assertRaises(ValidationError):
            run_agent(args)


if __name__ == "__main__":
    unittest.main()
