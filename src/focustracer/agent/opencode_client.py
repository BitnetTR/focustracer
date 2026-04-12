from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any, Generator

from focustracer.agent.base import BaseAIAgent
from focustracer.agent.ollama_client import OllamaClient
from focustracer.core.targeting import TargetManifest


class OpenCodeClient(BaseAIAgent):
    def __init__(
        self,
        model: str,
        opencode_cmd: str = "opencode",
    ):
        super().__init__(model=model)
        self.opencode_cmd = opencode_cmd
        self._opencode_cmd_parts = shlex.split(opencode_cmd, posix=False)

    def _compose(self, *parts: str) -> list[str]:
        return [*self._opencode_cmd_parts, *parts]

    def _run(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except FileNotFoundError:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=True,
            )

    def generate(self, prompt: str, **kwargs) -> str:
        timeout = int(kwargs.get("timeout", 120))
        cmd = self._compose("run", "-m", kwargs.get("model", self.model), prompt)
        result = self._run(cmd, timeout=timeout)

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(stderr or "OpenCode command failed")

        return (result.stdout or "").strip()

    def generate_stream(self, prompt: str, **kwargs) -> Generator[str, None, None]:
        yield self.generate(prompt, **kwargs)

    def list_models(self) -> list[dict[str, Any]]:
        # OpenCode CLI currently does not expose a stable machine-readable model listing command.
        return []

    def health(self) -> dict[str, Any]:
        try:
            result = self._run(self._compose("--version"), timeout=15)
            ok = result.returncode == 0
            return {
                "ok": ok,
                "agent": "opencode",
                "model": self.model,
                "model_available": ok,
                "opencode_cmd": self.opencode_cmd,
                "version": (result.stdout or "").strip() if ok else None,
                "error": ((result.stderr or "").strip() or (result.stdout or "").strip())
                if not ok
                else None,
            }
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {
                "ok": False,
                "agent": "opencode",
                "model": self.model,
                "model_available": False,
                "opencode_cmd": self.opencode_cmd,
                "error": str(exc),
            }

    def suggest_targets(
        self,
        inventory: dict[str, Any],
        *,
        manual_targets: dict[str, Any] | None = None,
        error_context: str | None = None,
        user_hint: str | None = None,
    ) -> dict[str, Any]:
        prompt = (
            "You are selecting runtime tracing targets for a Python debugger.\n"
            "Return ONLY a JSON object with keys functions, files, lines, thread_names.\n"
            "Do not invent functions that are not in the inventory.\n"
            "At least one function must be selected.\n\n"
            f"Inventory:\n{json.dumps(inventory, indent=2)}\n\n"
            f"Manual targets:\n{json.dumps(manual_targets or {}, indent=2)}\n\n"
            f"User hint:\n{user_hint or ''}\n\n"
            f"Error context:\n{error_context or ''}\n"
        )
        response = self.generate(prompt)
        manifest = OllamaClient._extract_manifest(response)
        manifest = OllamaClient._align_manifest_with_inventory(manifest, inventory)
        if not manifest.functions:
            fallback_functions = OllamaClient._fallback_functions(inventory, user_hint)
            fallback_threads = OllamaClient._fallback_thread_names(inventory)
            manifest = manifest.merge(
                TargetManifest(functions=fallback_functions, thread_names=fallback_threads)
            )
        return manifest.to_dict()

    def analyze_trace(
        self,
        trace_file: str,
        source_file: str,
        *,
        error_context: str | None = None,
    ) -> str:
        prompt = (
            "Analyze the Python trace and source file and explain likely root cause.\n"
            "Provide next tracing focus recommendations.\n\n"
            f"Source file: {source_file}\n"
            f"Trace file: {trace_file}\n"
            f"Error context: {error_context or ''}\n"
        )
        return self.generate(prompt, timeout=180)