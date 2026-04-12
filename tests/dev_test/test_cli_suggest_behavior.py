from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from focustracer import cli


class _DummyAgent:
    def health(self):
        return {"ok": True, "model_available": True}

    def suggest_targets(self, *args, **kwargs):
        return {
            "functions": ["cli_sample_app.worker"],
            "files": ["cli_sample_app.py"],
            "lines": [],
            "thread_names": ["CLI-Worker"],
        }


class SuggestTargetsBehaviorTests(unittest.TestCase):
    def test_build_agent_supports_opencode(self):
        agent = cli._build_agent(
            agent_name="opencode",
            model="opencode/minimax-m2.5-free",
            base_url="http://localhost:11434",
            opencode_cmd="opencode",
        )
        self.assertEqual(agent.__class__.__name__, "OpenCodeClient")

    def test_suggest_targets_writes_manifest_when_requested(self):
        parser = cli.create_parser()
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "suggested.targets.json"
            args = parser.parse_args(
                [
                    "suggest-targets",
                    "--project-root",
                    "tests/fixtures",
                    "--target-script",
                    "tests/fixtures/cli_sample_app.py",
                    "--manifest-output",
                    str(output_path),
                ]
            )

            with patch("focustracer.cli._build_agent", return_value=_DummyAgent()):
                stdout_capture = io.StringIO()
                with redirect_stdout(stdout_capture):
                    exit_code = cli.suggest_targets(args)

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("cli_sample_app.worker", data["functions"])

    def test_suggest_targets_terminal_only_without_manifest_flags(self):
        parser = cli.create_parser()
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = parser.parse_args(
                [
                    "suggest-targets",
                    "--project-root",
                    "tests/fixtures",
                    "--target-script",
                    "tests/fixtures/cli_sample_app.py",
                    "--output-dir",
                    tmp_dir,
                ]
            )

            with patch("focustracer.cli._build_agent", return_value=_DummyAgent()):
                stdout_capture = io.StringIO()
                with redirect_stdout(stdout_capture):
                    exit_code = cli.suggest_targets(args)

            self.assertEqual(exit_code, 0)
            json.loads(stdout_capture.getvalue())
            created_files = [path for path in Path(tmp_dir).glob("*") if path.is_file()]
            self.assertEqual(created_files, [])

    def test_suggest_targets_execute_runs_trace_pipeline_with_merged_manifest(self):
        parser = cli.create_parser()
        args = parser.parse_args(
            [
                "suggest-targets",
                "--project-root",
                "tests/fixtures",
                "--target-script",
                "tests/fixtures/cli_sample_app.py",
                "--execute",
            ]
        )

        with patch("focustracer.cli._build_agent", return_value=_DummyAgent()):
            with patch("focustracer.cli._execute_trace_with_manifest", return_value=0) as execute_mock:
                stdout_capture = io.StringIO()
                with redirect_stdout(stdout_capture):
                    exit_code = cli.suggest_targets(args)

        self.assertEqual(exit_code, 0)
        execute_mock.assert_called_once()
        merged_manifest = execute_mock.call_args.args[1]
        self.assertIn("cli_sample_app.worker", merged_manifest.functions)


if __name__ == "__main__":
    unittest.main()
