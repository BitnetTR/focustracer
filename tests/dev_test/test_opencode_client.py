from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from focustracer.agent.opencode_client import OpenCodeClient


class OpenCodeClientTests(unittest.TestCase):
    def test_health_reports_ok_when_version_command_succeeds(self):
        client = OpenCodeClient(model="opencode/minimax-m2.5-free", opencode_cmd="opencode")

        completed = subprocess.CompletedProcess(
            args=["opencode", "--version"], returncode=0, stdout="1.0.0\n", stderr=""
        )
        with patch.object(client, "_run", return_value=completed):
            health = client.health()

        self.assertTrue(health["ok"])
        self.assertTrue(health["model_available"])

    def test_generate_raises_for_failed_command(self):
        client = OpenCodeClient(model="opencode/minimax-m2.5-free", opencode_cmd="opencode")

        completed = subprocess.CompletedProcess(
            args=["opencode", "run"], returncode=1, stdout="", stderr="model not found"
        )
        with patch.object(client, "_run", return_value=completed):
            with self.assertRaises(RuntimeError):
                client.generate("hello")

    def test_suggest_targets_parses_manifest_from_output(self):
        client = OpenCodeClient(model="opencode/minimax-m2.5-free", opencode_cmd="opencode")

        completed = subprocess.CompletedProcess(
            args=["opencode", "run"],
            returncode=0,
            stdout='{"functions":["worker"],"thread_names":["CLI-Worker"]}',
            stderr="",
        )
        inventory = {
            "project_root": "tests/fixtures",
            "target_script": "tests/fixtures/cli_sample_app.py",
            "functions": [
                "cli_sample_app.multiply",
                "cli_sample_app.process",
                "cli_sample_app.worker",
            ],
            "loops": [],
            "thread_entries": [
                {
                    "file": "cli_sample_app.py",
                    "line": 19,
                    "name": "CLI-Worker",
                    "target": "worker",
                }
            ],
        }

        with patch.object(client, "_run", return_value=completed):
            manifest = client.suggest_targets(inventory, user_hint="trace worker")

        self.assertEqual(manifest["functions"], ["cli_sample_app.worker"])
        self.assertEqual(manifest["thread_names"], ["CLI-Worker"])


if __name__ == "__main__":
    unittest.main()
