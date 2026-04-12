from __future__ import annotations

import unittest
from unittest.mock import patch

from focustracer.agent.ollama_client import OllamaClient


class OllamaTargetSuggestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = {
            "project_root": "tests/fixtures",
            "target_script": "tests/fixtures/cli_sample_app.py",
            "functions": [
                "cli_sample_app.multiply",
                "cli_sample_app.process",
                "cli_sample_app.worker",
            ],
            "loops": [
                {
                    "file": "cli_sample_app.py",
                    "line": 9,
                    "type": "for",
                    "function": "cli_sample_app.process",
                }
            ],
            "thread_entries": [
                {
                    "file": "cli_sample_app.py",
                    "line": 19,
                    "name": "CLI-Worker",
                    "target": "worker",
                }
            ],
        }

    def test_extract_manifest_accepts_python_literal_and_alias_keys(self):
        raw = """```\n{'function': 'worker', 'threads': ['CLI-Worker']}\n```"""
        manifest = OllamaClient._extract_manifest(raw)

        self.assertEqual(manifest.functions, ["worker"])
        self.assertEqual(manifest.thread_names, ["CLI-Worker"])

    def test_suggest_targets_aligns_alias_keys_to_inventory(self):
        client = OllamaClient(model="qwen2.5:3b", base_url="http://localhost:11434")
        raw = '{"functions": ["worker"], "threads": ["CLI-Worker"]}'

        with patch.object(client, "generate", return_value=raw):
            result = client.suggest_targets(self.inventory, user_hint="trace worker")

        self.assertEqual(result["functions"], ["cli_sample_app.worker"])
        self.assertEqual(result["thread_names"], ["CLI-Worker"])

    def test_suggest_targets_falls_back_when_model_output_is_not_json(self):
        client = OllamaClient(model="qwen2.5:3b", base_url="http://localhost:11434")

        with patch.object(
            client,
            "generate",
            return_value="Trace worker flow in CLI-Worker and focus on multiplication path.",
        ):
            result = client.suggest_targets(
                self.inventory,
                user_hint="Trace the worker path and multiplication logic",
            )

        self.assertIn("cli_sample_app.worker", result["functions"])
        self.assertIn("CLI-Worker", result["thread_names"])

    def test_suggest_targets_retries_with_compact_prompt_when_first_pass_is_empty(self):
        client = OllamaClient(model="qwen2.5:3b", base_url="http://localhost:11434")
        side_effect = [
            '{"functions": ["unknown.fn"], "files": [], "lines": [], "thread_names": []}',
            '{"functions": ["cli_sample_app.worker"], "files": ["cli_sample_app.py"], "lines": [], "thread_names": ["CLI-Worker"]}',
        ]

        with patch.object(client, "generate", side_effect=side_effect) as generate_mock:
            result = client.suggest_targets(self.inventory, user_hint="trace worker")

        self.assertEqual(result["functions"], ["cli_sample_app.worker"])
        self.assertIn("CLI-Worker", result["thread_names"])
        self.assertEqual(generate_mock.call_count, 2)
        retry_prompt = generate_mock.call_args_list[1].args[0]
        self.assertIn("AVAILABLE_FUNCTIONS", retry_prompt)


if __name__ == "__main__":
    unittest.main()
