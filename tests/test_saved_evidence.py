"""Verify archived run invariants without calling models or reading credentials."""

import json
import unittest
from decimal import Decimal

from src.shortvideo_agent.config import PROJECT_ROOT
from src.shortvideo_agent.contracts import RESULT, TRACE
from src.shortvideo_agent.io_utils import read_json
from src.shortvideo_agent.evaluation import repo_path
from src.shortvideo_agent.materials import load_assets
from src.shortvideo_agent.tools import check_rules, estimate_duration, script_identity


class SavedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = PROJECT_ROOT / "examples/phase04"

    def bundles(self):
        for root in (self.root, PROJECT_ROOT / "examples/phase05"):
            for directory in sorted(root.iterdir()):
                if directory.is_dir() and (directory / "result.json").exists():
                    yield directory, read_json(directory / "result.json", RESULT), read_json(directory / "trace.json", TRACE)

    def test_saved_contracts_journals_counts_and_modes_agree(self):
        count = 0
        for directory, result, trace in self.bundles():
            with self.subTest(directory=directory.name):
                count += 1
                self.assertEqual(result["run_id"], trace["run_id"])
                self.assertEqual(result["mode"], trace["mode"])
                self.assertEqual(result["status"], trace["final_status"])
                self.assertLessEqual(trace["model_calls"], trace["limits"]["max_steps"])
                self.assertLessEqual(trace["tool_calls"], trace["limits"]["max_tool_calls"])
                self.assertEqual([event["step"] for event in trace["events"]], list(range(1, len(trace["events"]) + 1)))
                journal = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(journal, trace["events"])
                self.assertEqual(sum(event["kind"] == "model_request" for event in journal), trace["model_calls"])
                self.assertEqual(sum(event["kind"] == "tool_call" for event in journal), trace["tool_calls"])
                self.assertEqual(journal[-1]["kind"], "final")
        self.assertGreaterEqual(count, 6)

    def test_saved_success_checks_match_and_recompute(self):
        for directory, result, trace in self.bundles():
            if result["status"] != "success":
                continue
            with self.subTest(directory=directory.name):
                materials, rules = load_assets(repo_path(trace["metadata"]["materials_file"], metadata=True),
                                              repo_path(trace["metadata"]["rules_file"], metadata=True))
                script = result["script"]
                identity = script_identity(script)
                self.assertEqual({check["tool"] for check in result["checks"]}, {"estimate_duration", "check_rules"})
                for check in result["checks"]:
                    self.assertTrue(check["passed"])
                    self.assertEqual(check["script_sha256"], identity["script_sha256"])
                    self.assertEqual(check["script_revision"], script["revision"])
                total = sum(Decimal(str(scene["estimated_duration_seconds"])) for scene in script["scenes"])
                self.assertEqual(total, Decimal(str(script["estimated_total_seconds"])))
                timing = estimate_duration(script, result["brief"]["target_duration_seconds"])
                self.assertTrue(timing["passed"])
                self.assertEqual(timing["details"]["estimated_total_seconds"], script["estimated_total_seconds"])
                self.assertTrue(check_rules(script, materials, rules, product_id=result["brief"]["product_id"])["passed"])

    def test_real_repair_and_no_material_paths_have_observation_then_action(self):
        _, repair, trace = next(bundle for bundle in self.bundles() if bundle[0].name == "real-overlong-repair")
        self.assertEqual(repair["mode"], "real")
        self.assertEqual(trace["metadata"]["initial_script_origin"], "provided_input")
        timings = [event for event in trace["events"] if event["kind"] == "tool_result" and event["action"] == "estimate_duration"]
        self.assertFalse(timings[0]["observation"]["result"]["passed"])
        self.assertTrue(timings[-1]["observation"]["result"]["passed"])
        new_drafts = [event for event in trace["events"] if event["kind"] == "draft_registered" and event["step"] > timings[0]["step"]]
        self.assertTrue(new_drafts)
        _, empty, empty_trace = next(bundle for bundle in self.bundles() if bundle[0].name == "real-no-materials")
        self.assertEqual(empty["status"], "needs_input")
        self.assertIsNone(empty["script"])
        self.assertTrue(empty["requests_for_input"])
        searches = [event for event in empty_trace["events"] if event["kind"] == "tool_result" and event["action"] == "search_materials"]
        self.assertTrue(searches)
        self.assertTrue(all(event["observation"]["result"]["matched_count"] == 0 for event in searches))


if __name__ == "__main__":
    unittest.main()
