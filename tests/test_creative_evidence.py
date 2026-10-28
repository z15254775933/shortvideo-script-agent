"""Actual archived creative reviews remain auditable without API access."""

import copy
import unittest
from unittest.mock import patch

from src.shortvideo_agent.config import PROJECT_ROOT, Settings
from src.shortvideo_agent.evaluation import AuditError, audit_bundle, audit_case, verify_loaded
from src.shortvideo_agent.models import DeepSeekClient


class CreativeEvidenceTests(unittest.TestCase):
    def bundle(self):
        return audit_bundle(PROJECT_ROOT / "examples/phase06/creative-douyin")

    def test_actual_creative_bundle_replays_without_credentials_or_network(self):
        with patch.object(Settings, "load", side_effect=AssertionError("credentials accessed")), \
                patch.object(DeepSeekClient, "complete", side_effect=AssertionError("network called")):
            bundle = self.bundle()
            self.assertEqual(bundle["result"]["status"], "success")
            self.assertEqual(bundle["result"]["writing_mode"], "creative")

    def test_missing_review_records_or_hidden_review_calls_are_rejected(self):
        bundle = self.bundle()
        for field, value in (("review_records", []), ("review_model_calls", 0), ("total_model_calls", 0)):
            trace = copy.deepcopy(bundle["trace"])
            trace["metadata"][field] = value
            with self.subTest(field=field), self.assertRaises(AuditError):
                verify_loaded(bundle["result"], trace, trace["events"], bundle["materials"], bundle["rules"])

    def test_edited_review_response_cannot_keep_old_verdict(self):
        bundle = self.bundle()
        trace = copy.deepcopy(bundle["trace"])
        trace["metadata"]["review_records"][0]["content"] = '{"fields":[]}'
        with self.assertRaises(ValueError):
            verify_loaded(bundle["result"], trace, trace["events"], bundle["materials"], bundle["rules"])

    def test_review_input_changes_invalidate_the_saved_fingerprint(self):
        bundle = self.bundle()
        trace = copy.deepcopy(bundle["trace"])
        trace["metadata"]["review_records"][0]["input"]["fields"][0]["text"] = "changed"
        with self.assertRaises(AuditError):
            verify_loaded(bundle["result"], trace, trace["events"], bundle["materials"], bundle["rules"])

    def test_format_failure_is_not_credited_as_valid_semantic_rejection(self):
        with self.assertRaises(AuditError):
            audit_case({"kind": "creative_repair", "paths": ["examples/phase06/creative-semantic-repair"]})

    def test_observed_workflow_false_positive_is_rejected_by_current_checks(self):
        with self.assertRaises(AuditError):
            audit_bundle(PROJECT_ROOT / "examples/phase06/creative-douyin-compact")


if __name__ == "__main__":
    unittest.main()
