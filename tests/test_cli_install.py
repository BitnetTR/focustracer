from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from focustracer import cli


class _FakeOpenCodeClient:
    def __init__(self, model: str, opencode_cmd: str):
        self.model = model
        self.opencode_cmd = opencode_cmd

    def health(self):
        if self.opencode_cmd == "python -m opencode":
            return {
                "ok": True,
                "version": "module-mode",
                "error": None,
                "model_available": True,
            }
        return {
            "ok": False,
            "version": None,
            "error": "command not found",
            "model_available": False,
        }


class InstallFlowTests(unittest.TestCase):
    def test_check_opencode_status_falls_back_to_python_module_command(self):
        with patch("focustracer.cli.OpenCodeClient", _FakeOpenCodeClient):
            status = cli._check_opencode_status(opencode_cmd="opencode", model=cli.DEFAULT_MODEL)

        self.assertTrue(status["installed"])
        self.assertEqual(status["detected_command"], "python -m opencode")
        self.assertEqual(status["version"], "module-mode")

    def test_install_status_mode_prints_snapshot_and_exits(self):
        args = argparse.Namespace(
            status=True,
            agent=None,
            model=cli.DEFAULT_MODEL,
            ollama_url="http://localhost:11434",
            opencode_cmd="opencode",
        )

        with patch("focustracer.cli._check_ollama_status", return_value={"installed": False}):
            with patch("focustracer.cli._check_opencode_status", return_value={"installed": True}):
                with patch("focustracer.cli._print_status_panel") as panel_mock:
                    rc = cli.install_agent(args)

        self.assertEqual(rc, 0)
        panel_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
