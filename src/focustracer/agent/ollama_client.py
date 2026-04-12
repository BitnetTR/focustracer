from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Generator

import requests

from focustracer.agent.base import BaseAIAgent
from focustracer.core.targeting import TargetManifest


class OllamaClient(BaseAIAgent):
    def __init__(
        self,
        model: str = "qwen2.5:3b",
        base_url: str = "http://localhost:11434",
    ):
        super().__init__(model=model)
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()

    def _fetch_tags(self) -> dict[str, Any]:
        response = self._session.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()
        return response.json()

    def generate(self, prompt: str, **kwargs) -> str:
        payload = {
            "model": kwargs.get("model", self.model),
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.1),
                "top_p": kwargs.get("top_p", 0.9),
                "num_predict": kwargs.get("max_tokens", 1024),
            },
        }
        response_format = kwargs.get("response_format")
        if response_format is not None:
            payload["format"] = response_format

        keep_alive = kwargs.get("keep_alive")
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        timeout = kwargs.get("timeout", 120)
        retries = max(int(kwargs.get("retries", 1)), 1)
        last_error: requests.RequestException | None = None

        for attempt in range(retries):
            try:
                response = self._session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("error"):
                    raise RuntimeError(str(data["error"]))
                return data.get("response", "")
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 >= retries:
                    raise

        if last_error is not None:
            raise last_error
        return ""

    def generate_stream(self, prompt: str, **kwargs) -> Generator[str, None, None]:
        payload = {
            "model": kwargs.get("model", self.model),
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", 0.1),
                "top_p": kwargs.get("top_p", 0.9),
                "num_predict": kwargs.get("max_tokens", 1024),
            },
        }
        response = self._session.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=kwargs.get("timeout", 120),
            stream=True,
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise RuntimeError(str(data["error"]))
            if "response" in data:
                yield data["response"]
            if data.get("done"):
                break

    def list_models(self) -> list[dict[str, Any]]:
        try:
            return self._fetch_tags().get("models", [])
        except requests.RequestException:
            return []

    def health(self) -> dict[str, Any]:
        try:
            models = self._fetch_tags().get("models", [])
            model_names = [model.get("name", "") for model in models]
            return {
                "ok": True,
                "base_url": self.base_url,
                "model": self.model,
                "model_available": self.model in model_names,
                "available_models": model_names,
            }
        except requests.RequestException as exc:
            return {
                "ok": False,
                "base_url": self.base_url,
                "model": self.model,
                "model_available": False,
                "error": str(exc),
                "available_models": [],
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
        response = self.generate(
            prompt,
            temperature=0.0,
            top_p=0.2,
            response_format=self._manifest_response_format(),
            retries=2,
        )
        manifest = self._extract_manifest(response)
        manifest = self._align_manifest_with_inventory(manifest, inventory)

        if not manifest.functions:
            retry_response = self.generate(
                self._target_selection_retry_prompt(inventory, user_hint),
                temperature=0.0,
                top_p=0.2,
                max_tokens=512,
                response_format=self._manifest_response_format(),
                retries=2,
            )
            retry_manifest = self._align_manifest_with_inventory(
                self._extract_manifest(retry_response),
                inventory,
            )
            manifest = manifest.merge(retry_manifest)

        if not manifest.functions:
            fallback_functions = self._fallback_functions(inventory, user_hint)
            fallback_threads = self._fallback_thread_names(inventory)
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
        trace_text = Path(trace_file).read_text(encoding="utf-8")
        source_text = Path(source_file).read_text(encoding="utf-8")
        prompt = (
            "Analyze the following Python trace and source file.\n"
            "Explain the likely root cause and recommend the next tracing focus.\n\n"
            f"Error context:\n{error_context or ''}\n\n"
            f"Source:\n{source_text[:20000]}\n\n"
            f"Trace:\n{trace_text[:30000]}"
        )
        return self.generate(prompt, max_tokens=2048)

    @staticmethod
    def _extract_manifest(raw_response: str) -> TargetManifest:
        def _attempt_parse(payload: str) -> dict[str, Any] | None:
            try:
                parsed = json.loads(payload)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                pass

            try:
                parsed = ast.literal_eval(payload)
                return parsed if isinstance(parsed, dict) else None
            except (ValueError, SyntaxError):
                return None

        response = raw_response.strip()
        if "```json" in response:
            response = response.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in response:
            response = response.split("```", 1)[1].split("```", 1)[0]

        parsed = _attempt_parse(response)
        if parsed is None:
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1 and end > start:
                parsed = _attempt_parse(response[start : end + 1])

        if parsed is not None:
            return TargetManifest.from_dict(OllamaClient._coerce_manifest_payload(parsed))

        extracted = OllamaClient._extract_keyed_lists(response)
        return TargetManifest.from_dict(extracted)

    @staticmethod
    def _coerce_manifest_payload(payload: dict[str, Any]) -> dict[str, Any]:
        def _as_list(value: Any) -> list[str]:
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item) for item in value]
            return [str(value)]

        return {
            "functions": _as_list(
                payload.get("functions")
                or payload.get("function")
                or payload.get("target_functions")
            ),
            "files": _as_list(payload.get("files") or payload.get("file") or payload.get("target_files")),
            "lines": _as_list(payload.get("lines") or payload.get("line") or payload.get("target_lines")),
            "thread_names": _as_list(
                payload.get("thread_names")
                or payload.get("threadNames")
                or payload.get("threads")
                or payload.get("thread")
                or payload.get("target_threads")
            ),
        }

    @staticmethod
    def _extract_keyed_lists(raw_response: str) -> dict[str, list[str]]:
        patterns = {
            "functions": ["functions", "function", "target_functions"],
            "files": ["files", "file", "target_files"],
            "lines": ["lines", "line", "target_lines"],
            "thread_names": [
                "thread_names",
                "threadNames",
                "threads",
                "thread",
                "target_threads",
            ],
        }
        result: dict[str, list[str]] = {
            "functions": [],
            "files": [],
            "lines": [],
            "thread_names": [],
        }

        for canonical_key, aliases in patterns.items():
            for key in aliases:
                list_pattern = re.compile(
                    rf"['\"]?{re.escape(key)}['\"]?\s*:\s*\[(?P<body>.*?)\]",
                    flags=re.IGNORECASE | re.DOTALL,
                )
                match = list_pattern.search(raw_response)
                if match:
                    body = match.group("body")
                    values = re.findall(r"['\"]([^'\"]+)['\"]", body)
                    result[canonical_key].extend(values)
                    continue

                scalar_pattern = re.compile(
                    rf"['\"]?{re.escape(key)}['\"]?\s*:\s*['\"](?P<value>[^'\"]+)['\"]",
                    flags=re.IGNORECASE,
                )
                scalar_match = scalar_pattern.search(raw_response)
                if scalar_match:
                    result[canonical_key].append(scalar_match.group("value"))

        return result

    @staticmethod
    def _align_manifest_with_inventory(
        manifest: TargetManifest,
        inventory: dict[str, Any],
    ) -> TargetManifest:
        available_functions = [str(item) for item in inventory.get("functions", []) if str(item).strip()]
        available_function_set = set(available_functions)
        resolved_functions: list[str] = []

        for function_name in manifest.functions:
            candidate = function_name.strip().strip("`").replace("()", "")
            if not candidate:
                continue
            if candidate in available_function_set:
                resolved_functions.append(candidate)
                continue

            tail = candidate.split(".")[-1]
            matches = [name for name in available_functions if name.endswith(f".{candidate}")]
            if not matches:
                matches = [name for name in available_functions if name.endswith(f".{tail}")]
            if matches:
                resolved_functions.append(sorted(matches)[0])

        available_files = {
            str(item.get("file"))
            for item in inventory.get("loops", []) + inventory.get("thread_entries", [])
            if isinstance(item, dict) and item.get("file")
        }
        target_script = inventory.get("target_script")
        if target_script:
            available_files.add(Path(str(target_script)).name)

        available_thread_names = {
            str(item.get("name"))
            for item in inventory.get("thread_entries", [])
            if isinstance(item, dict) and item.get("name")
        }

        return TargetManifest(
            functions=resolved_functions,
            files=[value for value in manifest.files if value in available_files] if available_files else manifest.files,
            lines=list(manifest.lines),
            thread_names=[value for value in manifest.thread_names if value in available_thread_names]
            if available_thread_names
            else manifest.thread_names,
        ).normalized()

    @staticmethod
    def _fallback_functions(inventory: dict[str, Any], user_hint: str | None) -> list[str]:
        available_functions = [str(item) for item in inventory.get("functions", []) if str(item).strip()]
        if not available_functions:
            return []

        hint_words = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", (user_hint or "").lower()))
        scored: list[tuple[int, str]] = []
        for function_name in available_functions:
            lower_name = function_name.lower()
            tail = lower_name.split(".")[-1]
            score = 0
            for word in hint_words:
                if word == tail:
                    score += 4
                elif word in tail:
                    score += 3
                elif word in lower_name:
                    score += 2
            if score > 0:
                scored.append((score, function_name))

        if scored:
            scored.sort(key=lambda item: (-item[0], item[1]))
            return [name for _, name in scored[:3]]

        targets = [
            str(entry.get("target"))
            for entry in inventory.get("thread_entries", [])
            if isinstance(entry, dict) and entry.get("target")
        ]
        resolved_from_threads: list[str] = []
        for target in targets:
            matches = [name for name in available_functions if name.endswith(f".{target}") or name == target]
            resolved_from_threads.extend(matches)

        if resolved_from_threads:
            return sorted(set(resolved_from_threads))[:3]

        target_script_stem = Path(str(inventory.get("target_script", ""))).stem
        script_matches = [
            function_name
            for function_name in available_functions
            if target_script_stem and function_name.startswith(f"{target_script_stem}.")
        ]
        if script_matches:
            return sorted(script_matches)[:3]

        return sorted(available_functions)[:1]

    @staticmethod
    def _fallback_thread_names(inventory: dict[str, Any]) -> list[str]:
        names = {
            str(item.get("name"))
            for item in inventory.get("thread_entries", [])
            if isinstance(item, dict) and item.get("name")
        }
        return sorted(names)

    @staticmethod
    def _manifest_response_format() -> str:
        return "json"

    @staticmethod
    def _target_selection_retry_prompt(
        inventory: dict[str, Any],
        user_hint: str | None,
    ) -> str:
        available_functions = [str(item) for item in inventory.get("functions", []) if str(item).strip()]
        available_threads = [
            str(item.get("name"))
            for item in inventory.get("thread_entries", [])
            if isinstance(item, dict) and item.get("name")
        ]
        available_files = sorted(
            {
                str(item.get("file"))
                for item in inventory.get("loops", []) + inventory.get("thread_entries", [])
                if isinstance(item, dict) and item.get("file")
            }
        )
        return (
            "Return ONLY a JSON object with keys functions, files, lines, thread_names.\n"
            "Select at least one function from AVAILABLE_FUNCTIONS.\n"
            "Do not include values outside the available lists.\n\n"
            f"AVAILABLE_FUNCTIONS:\n{json.dumps(available_functions, indent=2)}\n\n"
            f"AVAILABLE_FILES:\n{json.dumps(available_files, indent=2)}\n\n"
            f"AVAILABLE_THREAD_NAMES:\n{json.dumps(sorted(set(available_threads)), indent=2)}\n\n"
            f"HINT:\n{user_hint or ''}\n"
        )
