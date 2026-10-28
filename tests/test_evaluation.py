"""Audit actual examples and reject misleading or altered evidence offline."""

import copy
import json
import unittest
from unittest.mock import patch

from src.shortvideo_agent.comparison import comparison_outcome, probe_contexts
from src.shortvideo_agent.config import PROJECT_ROOT, Settings
from src.shortvideo_agent.contracts import TRACE, ValidationError
from src.shortvideo_agent.evaluation import AuditError, audit_bundle, evaluate_manifest, repo_path, verify_loaded
from src.shortvideo_agent.io_utils import read_json
from src.shortvideo_agent.materials import load_assets
from src.shortvideo_agent.models import DeepSeekClient


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.manifest = PROJECT_ROOT / "data/evaluation_cases.json"

    def test_all_acceptance_cases_have_real_evidence_and_pass_offline_audit(self):
        report = evaluate_manifest(self.manifest)
        self.assertEqual({row["id"] for row in report["cases"]}, {"A01", "A02", "A03", "A04", "A05", "A06", "A07", "C01"})
        self.assertEqual(report["passed"], report["total"], report)
        self.assertEqual(report["new_model_calls"], 0)

    def test_evaluation_needs_neither_credentials_nor_network(self):
        with patch.object(Settings, "load", side_effect=AssertionError("credentials accessed")), \
                patch.object(DeepSeekClient, "complete", side_effect=AssertionError("network called")):
            self.assertEqual(evaluate_manifest(self.manifest)["passed"], 8)

    def test_changed_duration_or_text_cannot_keep_old_passed_checks(self):
        directory = PROJECT_ROOT / "examples/phase04/real-normal"
        bundle = audit_bundle(directory)
        trace = bundle["trace"]
        journal = trace["events"]
        for field in ("estimated_total_seconds", "title"):
            result = copy.deepcopy(bundle["result"])
            result["script"][field] = 1 if field == "estimated_total_seconds" else "changed"
            with self.subTest(field=field), self.assertRaises(AuditError):
                verify_loaded(result, trace, journal, bundle["materials"], bundle["rules"])

    def test_modes_and_journal_tampering_are_detected(self):
        bundle = audit_bundle(PROJECT_ROOT / "examples/phase04/real-normal")
        result = copy.deepcopy(bundle["result"])
        result["mode"] = "mock"
        with self.assertRaises(AuditError):
            verify_loaded(result, bundle["trace"], bundle["trace"]["events"], bundle["materials"], bundle["rules"])
        with self.assertRaises(AuditError):
            verify_loaded(bundle["result"], bundle["trace"], [], bundle["materials"], bundle["rules"])

    def test_evidence_paths_cannot_escape_repository(self):
        for value in ("../outside", "/outside", "C:/Windows/private", "//server/share/private"):
            with self.subTest(path=value), self.assertRaises(AuditError):
                repo_path(value)

    def test_windows_source_metadata_is_portable_and_cannot_target_credentials(self):
        actual = repo_path("F:/old-machine/repo/data/materials.json", metadata=True)
        self.assertEqual(actual, (PROJECT_ROOT / "data/materials.json").resolve())
        with self.assertRaises(AuditError):
            repo_path(".env", metadata=True)

    def test_probe_keeps_context_queries_and_prefix_identical(self):
        trace = read_json(PROJECT_ROOT / "examples/phase04/real-normal/trace.json", TRACE)
        materials, rules = load_assets(PROJECT_ROOT / "data/materials.json", PROJECT_ROOT / "data/brand_rules.json")
        shared, contexts = probe_contexts(trace, Settings("", "https://api.deepseek.com", trace["model"]), materials, rules)
        size = len(shared["messages"])
        self.assertEqual(contexts["available"]["messages"][:size], contexts["empty"]["messages"][:size])
        self.assertEqual([item["arguments"] for item in contexts["available"]["observations"]],
                         [item["arguments"] for item in contexts["empty"]["observations"]])
        self.assertTrue(all(item["observation"]["result"]["matched_count"] > 0 for item in contexts["available"]["observations"]))
        self.assertTrue(all(item["observation"]["result"]["matched_count"] == 0 for item in contexts["empty"]["observations"]))

    def test_probe_rejects_mock_provenance_and_changed_model(self):
        trace = read_json(PROJECT_ROOT / "examples/phase04/real-normal/trace.json", TRACE)
        materials, rules = load_assets(PROJECT_ROOT / "data/materials.json", PROJECT_ROOT / "data/brand_rules.json")
        for model, mode in ((trace["model"], "mock"), ("other-model", "real")):
            with self.subTest(model=model), self.assertRaises(ValidationError):
                probe_contexts({**trace, "mode": mode}, Settings("", "https://api.deepseek.com", model), materials, rules)

    def test_comparison_does_not_count_plain_text_or_unchanged_generation_as_adaptation(self):
        plain = {"content": "done", "tool_calls": []}
        action = {"tool_calls": [{"function": {"name": "estimate_duration", "arguments": json.dumps({"script": {}})}}]}
        self.assertFalse(comparison_outcome(plain, plain))
        self.assertFalse(comparison_outcome(action, action))


if __name__ == "__main__":
    unittest.main()
