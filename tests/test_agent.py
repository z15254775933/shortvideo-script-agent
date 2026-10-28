"""Scripted model fixtures validate runtime safeguards, not real model quality."""

import copy
import json
import unittest
from unittest.mock import patch

from src.shortvideo_agent.agent import Agent, render_markdown
from src.shortvideo_agent.config import PROJECT_ROOT, Settings
from src.shortvideo_agent.contracts import BRIEF, RESULT, SCRIPT, TRACE, validate
from src.shortvideo_agent.io_utils import read_json
from src.shortvideo_agent.materials import load_assets
from src.shortvideo_agent.mock import ScriptedAgentClient, tool_reply
from src.shortvideo_agent.models import ModelError, ModelReply
from src.shortvideo_agent.tools import ToolRegistry, script_identity


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.materials, self.rules = load_assets(PROJECT_ROOT / "data/materials.json", PROJECT_ROOT / "data/brand_rules.json")
        self.brief = read_json(PROJECT_ROOT / "examples/inputs/normal.json", BRIEF)
        self.short = read_json(PROJECT_ROOT / "examples/tool_inputs/within_budget.json", SCRIPT)
        self.long = read_json(PROJECT_ROOT / "examples/tool_inputs/overlong.json", SCRIPT)

    def action(self, name, **arguments):
        if name != "finish_task":
            arguments.setdefault("reason_summary", "固定测试动作，不是真实模型决策")
        return tool_reply(name, arguments)

    def finish(self, status="success", requests=None):
        return self.action("finish_task", status=status, reason="测试最终状态", requests_for_input=requests or [], risks=[])

    def search(self):
        return self.action("search_materials", query="字幕")

    def timing(self, script=None):
        return self.action("estimate_duration", script=self.short if script is None else script)

    def rules_check(self, script=None):
        return self.action("check_rules", script=self.short if script is None else script)

    def run_plan(self, replies, *, brief=None, initial=None, materials=None, failures=None, max_steps=10, max_tools=16):
        registry = ToolRegistry(self.materials if materials is None else materials, self.rules,
                                self.brief if brief is None else brief, failures=failures)
        settings = Settings("", "https://api.deepseek.com", "offline-scripted", max_steps=max_steps, max_tool_calls=max_tools)
        agent = Agent(ScriptedAgentClient(replies), settings, registry, mode="mock", initial_script=initial)
        result, trace = agent.run()
        validate(result, RESULT)
        validate(trace, TRACE)
        self.assertLessEqual(trace["model_calls"], max_steps)
        self.assertLessEqual(trace["tool_calls"], max_tools)
        return result, trace

    def errors(self, trace):
        return [event["observation"]["error"]["code"] for event in trace["events"]
                if event["kind"] == "tool_result" and event["observation"].get("status") == "error"]

    def test_success_uses_runtime_revisions_actual_estimates_and_both_checks(self):
        result, trace = self.run_plan([self.search(), self.timing(), self.rules_check(), self.finish()])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["script"]["revision"], 1)
        self.assertEqual(result["script"]["estimated_total_seconds"], 13.7)
        self.assertEqual({item["tool"] for item in result["checks"]}, {"estimate_duration", "check_rules"})
        identity = script_identity(result["script"])
        self.assertTrue(all(check["script_sha256"] == identity["script_sha256"] for check in result["checks"]))
        self.assertEqual(trace["tool_calls"], 4)

    def test_missing_input_is_answered_by_model_terminal_action(self):
        brief = {key: value for key, value in self.brief.items() if key != "target_duration_seconds"}
        result, trace = self.run_plan([self.finish("needs_input", ["目标时长是多少秒？"])], brief=brief)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(trace["model_calls"], 1)
        self.assertIsNone(result["script"])

    def test_premature_success_is_rejected_and_model_can_request_information(self):
        result, trace = self.run_plan([self.finish(), self.finish("needs_input", ["请补充资料"])])
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("final_evidence_missing", self.errors(trace))

    def test_no_sources_can_end_with_a_specific_request(self):
        materials = {**self.materials, "materials": []}
        result, trace = self.run_plan([self.search(), self.finish("needs_input", ["请补充产品事实资料"])], materials=materials)
        search_results = [event["observation"] for event in trace["events"] if event["kind"] == "tool_result" and event["action"] == "search_materials"]
        self.assertEqual(search_results[0]["result"]["matches"], [])
        self.assertEqual(result["status"], "needs_input")

    def test_edited_script_cannot_reuse_previous_rule_check(self):
        revised = copy.deepcopy(self.short)
        revised["scenes"][0]["min_visual_seconds"] = 6
        result, trace = self.run_plan([self.search(), self.timing(), self.rules_check(), self.timing(revised),
                                       self.finish(), self.rules_check(revised), self.finish()])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["script"]["revision"], 2)
        self.assertIn("final_evidence_missing", self.errors(trace))
        self.assertTrue(all(check["script_revision"] == 2 for check in result["checks"]))

    def test_model_cannot_assign_its_own_revision_or_estimate(self):
        spoofed = copy.deepcopy(self.short)
        spoofed["revision"] = 999
        spoofed["estimated_total_seconds"] = 0.1
        spoofed["scenes"][0]["estimated_duration_seconds"] = 0.1
        result, _ = self.run_plan([self.search(), self.timing(spoofed), self.rules_check(self.short), self.finish()])
        self.assertEqual(result["script"]["revision"], 1)
        self.assertEqual(result["script"]["estimated_total_seconds"], 13.7)

    def test_overlong_draft_requires_a_revised_candidate_and_new_checks(self):
        result, trace = self.run_plan([self.search(), self.timing(self.long), self.timing(), self.rules_check(), self.finish()])
        self.assertEqual(result["status"], "success")
        durations = [event["observation"]["result"]["details"]["estimated_total_seconds"] for event in trace["events"]
                     if event["kind"] == "tool_result" and event["action"] == "estimate_duration"]
        self.assertEqual(durations, [43.5, 13.7])
        self.assertEqual(result["script"]["revision"], 2)

    def test_source_retrieval_is_required_for_final_success(self):
        result, trace = self.run_plan([self.timing(), self.rules_check(), self.finish(), self.search(), self.finish()])
        self.assertEqual(result["status"], "success")
        self.assertIn("final_evidence_missing", self.errors(trace))

    def test_model_step_limit_returns_explicit_unfinished_state(self):
        result, trace = self.run_plan([self.search()], max_steps=1)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("模型决策步数上限", result["reason"])
        self.assertEqual(trace["model_calls"], 1)

    def test_tool_limit_applies_inside_a_multi_call_response(self):
        one, two = self.search(), self.timing()
        two.tool_calls[0]["id"] = "second_call"
        batch = ModelReply("offline-scripted", None, [*one.tool_calls, *two.tool_calls], "tool_calls", {})
        result, trace = self.run_plan([batch], max_tools=1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(trace["tool_calls"], 1)
        self.assertIsNone(result["script"])

    def test_finish_in_multi_call_batch_is_rejected_until_results_are_observed(self):
        parts = [self.timing(), self.rules_check(), self.finish()]
        for index, reply in enumerate(parts):
            reply.tool_calls[0]["id"] = f"call_{index}"
        batch = ModelReply("offline-scripted", None, [call for reply in parts for call in reply.tool_calls], "tool_calls", {})
        result, trace = self.run_plan([self.search(), batch, self.finish()])
        self.assertEqual(result["status"], "success")
        self.assertIn("finish_must_be_separate", self.errors(trace))

    def test_invalid_json_is_returned_as_feedback_not_executed(self):
        bad = tool_reply("search_materials", {})
        bad.tool_calls[0]["function"]["arguments"] = "{broken"
        result, trace = self.run_plan([bad, self.finish("incomplete")])
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("invalid_arguments", self.errors(trace))
        raw_calls = [event for event in trace["events"] if event["kind"] == "tool_call" and event["action"] == "search_materials"]
        self.assertEqual(raw_calls[0]["arguments"]["raw_arguments"], "{broken")

    def test_unknown_tool_cannot_execute_arbitrary_code(self):
        result, trace = self.run_plan([self.action("run_shell", command="not executed"), self.finish("incomplete")])
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("unknown_tool", self.errors(trace))

    def test_explicit_tool_failure_can_be_followed_by_a_new_model_action(self):
        result, trace = self.run_plan([self.search(), self.search(), self.timing(), self.rules_check(), self.finish()],
                                      failures={"search_materials": 1})
        self.assertEqual(result["status"], "success")
        self.assertIn("injected_failure", self.errors(trace))
        self.assertEqual(trace["model_calls"], 5)
        self.assertEqual(trace["metadata"]["evidence_scope"], "scripted_flow_only")

    def test_plain_text_alone_never_counts_as_completion(self):
        text = ModelReply("offline-scripted", "任务成功了", [], "stop", {})
        result, trace = self.run_plan([text, self.finish("incomplete")])
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(trace["model_calls"], 2)

    def test_model_connection_error_preserves_trace_and_does_not_fallback(self):
        registry = ToolRegistry(self.materials, self.rules, self.brief)
        client = ScriptedAgentClient([])
        with patch.object(client, "complete", side_effect=ModelError("network failed")):
            result, trace = Agent(client, Settings("", "https://api.deepseek.com", "test"), registry, mode="mock").run()
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(trace["model_calls"], 1)
        self.assertEqual(trace["tool_calls"], 0)

    def test_needs_input_requires_specific_questions(self):
        result, trace = self.run_plan([self.finish("needs_input"), self.finish("needs_input", ["请提供目标时长"])])
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("final_evidence_missing", self.errors(trace))

    def test_duplicate_ids_in_one_model_reply_are_rejected(self):
        batch = ModelReply("offline-scripted", None, [*self.search().tool_calls, *self.timing().tool_calls], "tool_calls", {})
        result, _ = self.run_plan([batch])
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("重复工具调用 ID", result["reason"])

    def test_initial_script_origin_is_explicit_and_real_checks_still_required(self):
        result, trace = self.run_plan([self.search(), self.timing(), self.rules_check(), self.finish()], initial=self.long)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["script"]["revision"], 2)
        self.assertEqual(trace["metadata"]["initial_script_origin"], "provided_input")

    def test_unchecked_or_unsupported_script_cannot_finish_successfully(self):
        bad = read_json(PROJECT_ROOT / "examples/tool_inputs/unsupported_claim.json", SCRIPT)
        result, trace = self.run_plan([self.search(), self.timing(bad), self.rules_check(bad), self.finish(), self.finish("incomplete")])
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("final_evidence_missing", self.errors(trace))

    def test_bad_action_summary_does_not_break_trace_structure(self):
        result, trace = self.run_plan([self.action("search_materials", query="字幕", reason_summary=["wrong type"]), self.finish("incomplete")])
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("invalid_arguments", self.errors(trace))

    def test_markdown_discloses_mock_mode_and_draft_status(self):
        result, _ = self.run_plan([self.search(), self.timing()], max_steps=2)
        markdown = render_markdown(result)
        self.assertIn("运行模式：mock", markdown)
        self.assertIn("未完成草稿", markdown)


if __name__ == "__main__":
    unittest.main()
