"""Boundary tests for step 2. No live API calls or business acceptance claims."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from src.shortvideo_agent.cli import main
from src.shortvideo_agent.config import ConfigError, PROJECT_ROOT, Settings
from src.shortvideo_agent.contracts import BRIEF, SCHEMAS, ValidationError, missing_fields, validate
from src.shortvideo_agent.io_utils import json_text, read_json, redact
from src.shortvideo_agent.materials import load_assets
from src.shortvideo_agent.models import DeepSeekClient, ModelError


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.brief = read_json(PROJECT_ROOT / "examples/inputs/normal.json", BRIEF)

    def invoke(self, *arguments):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(list(arguments))
        return code, json.loads(stream.getvalue())

    def test_duration_rejects_bool_zero_negative_nonfinite_and_strings(self):
        for invalid in (True, 0, -1, float("nan"), float("inf"), "30"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    validate({**self.brief, "target_duration_seconds": invalid}, BRIEF)

    def test_missing_duration_is_a_clarification_not_invalid_data(self):
        brief = read_json(PROJECT_ROOT / "examples/inputs/missing_duration.json", BRIEF)
        self.assertEqual(missing_fields(brief), ["target_duration_seconds"])
        with patch.object(Settings, "load", return_value=Settings("", "https://api.deepseek.com", "test")):
            code, output = self.invoke("inspect", "--input", str(PROJECT_ROOT / "examples/inputs/missing_duration.json"))
        self.assertEqual(code, 2)
        self.assertEqual(output["inspection_status"], "needs_input")
        self.assertTrue(output["not_a_script_generation_result"])

    def test_blank_fields_remain_missing_and_unknown_fields_fail(self):
        brief = {**self.brief, "audience": "  ", "style": None}
        validate(brief, BRIEF)
        self.assertEqual(missing_fields(brief), ["audience", "style"])
        with self.assertRaises(ValidationError):
            validate({**self.brief, "target_seconds": 30}, BRIEF)

    def test_json_rejects_duplicate_fields_and_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for text in ('{"schema_version":1,"schema_version":1}',
                         '{"schema_version":1,"target_duration_seconds":NaN}'):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    read_json(path, BRIEF)

    def test_assets_require_unique_fact_ids(self):
        materials = json.loads((PROJECT_ROOT / "data/materials.json").read_text(encoding="utf-8"))
        materials["materials"][1]["facts"][0]["fact_id"] = "P01-F01"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "materials.json"
            path.write_text(json.dumps(materials), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "Duplicate fact_id"):
                load_assets(path, PROJECT_ROOT / "data/brand_rules.json")

    def test_input_inspection_loads_assets_without_calling_model(self):
        with patch.object(DeepSeekClient, "complete", side_effect=AssertionError("unexpected network")), \
                patch.object(Settings, "load", return_value=Settings("", "https://api.deepseek.com", "test")):
            code, output = self.invoke("inspect", "--input", str(PROJECT_ROOT / "examples/inputs/normal.json"))
        self.assertEqual(code, 0)
        self.assertEqual(output["inspection_status"], "ready")
        self.assertEqual(output["assets"]["material_ids"], ["P01", "P02"])
        self.assertTrue(output["assets"]["materials_synthetic"])

    def test_environment_overrides_file_and_key_is_not_in_repr(self):
        fake_key = "sk-" + "x" * 32
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('DEEPSEEK_API_KEY="file-placeholder"\nAGENT_MAX_STEPS=8\n', encoding="utf-8")
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": fake_key}, clear=True):
                settings = Settings.load(path, require_key=True)
        self.assertEqual(settings.api_key, fake_key)
        self.assertEqual(settings.max_steps, 8)
        self.assertNotIn(fake_key, repr(settings))

    def test_mock_is_offline_explicit_and_independent_of_env_file(self):
        with patch.object(Settings, "load", side_effect=AssertionError("unexpected env access")):
            code, output = self.invoke("check-model", "--mode", "mock", "--env-file", "does-not-exist")
        self.assertEqual(code, 0)
        self.assertEqual(output["mode"], "mock")
        self.assertEqual(output["evidence_scope"], "flow_only")
        self.assertTrue(output["scripted"])

    def test_real_mode_requires_key_and_limits_are_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.env"
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(ConfigError):
                    Settings.load(path, require_key=True)
            with patch.dict("os.environ", {"AGENT_MAX_STEPS": "0"}, clear=True):
                with self.assertRaises(ConfigError):
                    Settings.load(path)

    def test_credentials_cannot_be_sent_to_another_host(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.env"
            for url in ("http://api.deepseek.com", "https://example.com", "https://api.deepseek.com@evil.example"):
                with self.subTest(url=url), patch.dict("os.environ", {"DEEPSEEK_BASE_URL": url}, clear=True):
                    with self.assertRaises(ConfigError):
                        Settings.load(path)

    def test_model_tool_call_survives_and_internal_reasoning_is_discarded(self):
        payload = {"model": "test-model", "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "reasoning_content": "must not be logged",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "search_materials", "arguments": '{"query":"字幕"}'}}],
        }}], "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}
        reply = DeepSeekClient._parse(payload)
        self.assertEqual(reply.assistant_message()["tool_calls"][0]["id"], "call_1")
        self.assertNotIn("reasoning_content", reply.assistant_message())
        self.assertEqual(reply.usage["total_tokens"], 15)

    def test_truncated_or_malformed_model_response_is_not_success(self):
        payload = {"model": "test", "choices": [{"finish_reason": "length", "message": {
            "role": "assistant", "content": "partial"}}]}
        for invalid in (payload, {"choices": []}, [], {"choices": "wrong"},
                        {"choices": [{"finish_reason": "stop", "message": []}]},
                        {"model": "test", "choices": [{"finish_reason": "tool_calls", "message": {
                            "role": "assistant", "content": "not actually a tool call"}}]}):
            with self.assertRaises(ModelError):
                DeepSeekClient._parse(invalid)

    def test_http_failure_does_not_leak_key_or_automatically_retry(self):
        fake_key = "sk-" + "x" * 32
        calls = []

        def fail(req, **kwargs):
            calls.append(req)
            raise HTTPError(req.full_url, 401, fake_key, {}, None)

        client = DeepSeekClient(Settings(fake_key, "https://api.deepseek.com", "test"), fail)
        with self.assertRaises(ModelError) as caught:
            client.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(len(calls), 1)
        self.assertIn("401", str(caught.exception))
        self.assertNotIn(fake_key, str(caught.exception))

    def test_diagnostic_output_redacts_nested_credentials(self):
        fake_key = "sk-" + "x" * 32
        value = {"nested": [{"text": "token=" + fake_key}], "Authorization": "Bearer secret"}
        self.assertNotIn(fake_key, json_text(value))
        self.assertEqual(redact(value)["Authorization"], "[REDACTED]")

    def test_existing_output_is_not_overwritten_and_model_is_not_called(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            path.write_text("keep this", encoding="utf-8")
            with patch.object(DeepSeekClient, "complete", side_effect=AssertionError("unexpected network")):
                code, _ = self.invoke("check-model", "--mode", "real", "--output", str(path))
            self.assertEqual(code, 4)
            self.assertEqual(path.read_text(encoding="utf-8"), "keep this")

    def test_all_schema_exports_are_serializable_and_brief_accepts_sample(self):
        for name in SCHEMAS:
            code, exported = self.invoke("schema", name)
            self.assertEqual(code, 0)
            self.assertEqual(exported["$schema"], "https://json-schema.org/draft/2020-12/schema")
        validate(copy.deepcopy(self.brief), SCHEMAS["brief"])


if __name__ == "__main__":
    unittest.main()
