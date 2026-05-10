from __future__ import annotations

import html
import json
import linecache
import os
import re
import sys
import threading
import time
import traceback as _traceback_module
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional
from xml.dom import minidom

from focustracer.core.targeting import TargetManifest, parse_line_filters


_CDATA_TAGS_RE = re.compile(
    r"(<(?:source|new|old)(?:\s[^>]*)?>)(.*?)(</(?:source|new|old)>)",
    re.DOTALL,
)


def _apply_cdata(xml_str: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        tag_open, content, tag_close = match.group(1), match.group(2), match.group(3)
        decoded = html.unescape(content)
        if decoded == content:
            return match.group(0)
        decoded = decoded.replace("]]>", "]]]]><![CDATA[>")
        return f"{tag_open}<![CDATA[{decoded}]]>{tag_close}"

    return _CDATA_TAGS_RE.sub(_repl, xml_str)


@dataclass
class _ThreadState:
    thread_name: str
    stack: list[str] = field(default_factory=list)
    prev_locals: dict[str, dict[str, tuple[str, str]]] = field(default_factory=dict)
    active_frames: int = 0


class TraceRecorder:
    def __init__(
        self,
        output_file: Optional[str] = None,
        max_depth: int = 100,
        track_variables: bool = True,
        track_arguments: bool = True,
        detail_level: str = "normal",
        output_format: str = "xml",
        enable_threading: bool = False,
        schema_version: str = "2.2",
        max_iterations: Optional[int] = None,
        target_functions: Optional[list[str]] = None,
        target_files: Optional[list[str]] = None,
        target_lines: Optional[list[str | int]] = None,
        target_threads: Optional[list[int]] = None,
        target_thread_names: Optional[list[str]] = None,
        manifest: Optional[TargetManifest] = None,
    ):
        self.max_depth = max_depth
        self.detail_level = detail_level.lower()
        self.output_format = output_format.lower()
        self.enable_threading = enable_threading
        self.schema_version = schema_version
        self.max_iterations = max_iterations

        if self.output_format not in {"xml", "json", "jsonl"}:
            raise ValueError("Invalid output format. Use xml, json, or jsonl.")
        if self.detail_level not in {"minimal", "normal", "detailed"}:
            raise ValueError("Invalid detail level. Use minimal, normal, or detailed.")

        resolved_manifest = manifest or TargetManifest.from_cli(
            functions=target_functions,
            files=target_files,
            lines=[str(value) for value in target_lines or []],
            thread_names=target_thread_names,
        )
        self.manifest = resolved_manifest.normalized()

        self.target_functions = set(self.manifest.functions) if self.manifest.functions else set()
        self.target_files = {
            self._normalize_path(value) for value in self.manifest.files if value.strip()
        }
        self.target_threads = set(target_threads or [])
        self.target_thread_names = set(self.manifest.thread_names)
        self.global_line_targets, self.file_line_targets = parse_line_filters(self.manifest.lines)
        self._has_function_targets = bool(self.target_functions)

        if self.detail_level == "minimal":
            self.track_variables = False
            self.track_arguments = False
        elif self.detail_level == "normal":
            self.track_variables = track_variables
            self.track_arguments = track_arguments
        else:
            self.track_variables = True
            self.track_arguments = True

        self.events: list[dict[str, Any]] = []
        self.event_id = 0
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.enabled = False
        self._lock = threading.RLock()
        self._thread_states: dict[int, _ThreadState] = {}
        self._forced_threads: dict[int, int] = {}

        self._stdlib_paths = {
            os.path.dirname(os.__file__),
            os.path.dirname(threading.__file__),
        }
        self._self_file = os.path.abspath(__file__)

        self._loop_compact_threshold = 2

        self.output_file = output_file or self._default_output_path()
        self.metadata = {
            "python_version": sys.version,
            "platform": sys.platform,
            "start_time": None,
            "end_time": None,
        }

    def _default_output_path(self) -> str:
        script_name = Path(sys.argv[0]).stem or "trace"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("output")
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / f"{timestamp}_{script_name}.{self.output_format}")

    @staticmethod
    def _normalize_path(path_value: str) -> str:
        return str(Path(path_value).as_posix())

    @staticmethod
    def _path_matches(target: str, candidate: str) -> bool:
        target_norm = str(Path(target).as_posix())
        candidate_norm = str(Path(candidate).as_posix())
        if candidate_norm == target_norm:
            return True
        if candidate_norm.endswith("/" + target_norm):
            return True
        return Path(candidate_norm).name == Path(target_norm).name

    def _is_stdlib(self, filename: str) -> bool:
        try:
            abs_path = os.path.abspath(filename)
        except OSError:
            return True
        if abs_path == self._self_file:
            return True
        if "<frozen" in filename or filename.startswith("<"):
            return True
        return any(abs_path.startswith(path) for path in self._stdlib_paths)

    @staticmethod
    def _format_value(value: Any) -> tuple[str, str]:
        try:
            type_name = type(value).__name__
            string_value = repr(value)
            if len(string_value) > 240:
                string_value = string_value[:237] + "..."
            return string_value, type_name
        except Exception as exc:
            return f"<unrepresentable: {exc}>", "unknown"

    @staticmethod
    def _get_source_line(filename: str, lineno: int) -> str:
        try:
            return linecache.getline(filename, lineno).strip()
        except Exception:
            return ""

    @staticmethod
    def _qualified_name(frame) -> str:
        module_name = frame.f_globals.get("__name__", "")
        qualname = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
        return ".".join(part for part in (module_name, qualname) if part)

    def _activation_candidates(self, frame) -> set[str]:
        code = frame.f_code
        module_name = frame.f_globals.get("__name__", "")
        qualname = getattr(code, "co_qualname", code.co_name)
        return {
            code.co_name,
            qualname,
            ".".join(part for part in (module_name, code.co_name) if part),
            ".".join(part for part in (module_name, qualname) if part),
        }

    def _extract_arguments(self, frame) -> dict[str, tuple[str, str]]:
        if not self.track_arguments:
            return {}
        arguments: dict[str, tuple[str, str]] = {}
        code = frame.f_code
        arg_names = code.co_varnames[: code.co_argcount + code.co_kwonlyargcount]
        for name in arg_names:
            if name in frame.f_locals:
                arguments[name] = self._format_value(frame.f_locals[name])
        return arguments

    def _extract_locals(self, frame) -> dict[str, tuple[str, str]]:
        if not self.track_variables:
            return {}
        locals_dict: dict[str, tuple[str, str]] = {}
        for name, value in frame.f_locals.items():
            if name.startswith("__"):
                continue
            locals_dict[name] = self._format_value(value)
        return locals_dict

    @staticmethod
    def _compute_delta(
        prev_locals: dict[str, dict[str, tuple[str, str]]],
        func_key: str,
        current_locals: dict[str, tuple[str, str]],
    ) -> dict[str, dict[str, str]]:
        previous = prev_locals.get(func_key, {})
        delta: dict[str, dict[str, str]] = {}

        for name, (value_str, type_name) in current_locals.items():
            if name not in previous:
                delta[name] = {"action": "added", "new": value_str, "type": type_name}
            elif previous[name][0] != value_str:
                delta[name] = {
                    "action": "changed",
                    "old": previous[name][0],
                    "new": value_str,
                    "type": type_name,
                }

        for name, (value_str, type_name) in previous.items():
            if name not in current_locals:
                delta[name] = {"action": "removed", "old": value_str, "type": type_name}

        prev_locals[func_key] = dict(current_locals)
        return delta

    def _thread_matches(self, thread_id: int, thread_name: str) -> bool:
        if self.target_threads and thread_id not in self.target_threads:
            return False
        if self.target_thread_names and thread_name not in self.target_thread_names:
            return False
        return True

    def _event_matches_scope_filters(
        self,
        filename: str,
        lineno: int,
        thread_id: int,
        thread_name: str,
    ) -> bool:
        if not self._thread_matches(thread_id, thread_name):
            return False

        if self.target_files and not any(
            self._path_matches(target, filename) for target in self.target_files
        ):
            return False

        if self.global_line_targets and lineno not in self.global_line_targets:
            return False

        if self.file_line_targets:
            matched_file = False
            for file_name, lines in self.file_line_targets.items():
                if self._path_matches(file_name, filename):
                    matched_file = True
                    if lineno not in lines:
                        return False
            if not matched_file:
                return False

        return True

    def _should_activate(self, frame, thread_id: int, thread_name: str) -> bool:
        if not self._thread_matches(thread_id, thread_name):
            return False
        if self._forced_threads.get(thread_id, 0) > 0:
            return True
        if not self._has_function_targets:
            return True
        return bool(self._activation_candidates(frame) & self.target_functions)

    def _ensure_thread_state(self, thread_id: int, thread_name: str) -> _ThreadState:
        state = self._thread_states.get(thread_id)
        if state is None:
            state = _ThreadState(thread_name=thread_name)
            self._thread_states[thread_id] = state
        else:
            state.thread_name = thread_name
        return state

    def _dispatch_trace(self, frame, event: str, arg: Any):
        if not self.enabled:
            return None

        thread_id = threading.get_ident()
        thread_name = threading.current_thread().name

        if event != "call":
            if thread_id in self._thread_states:
                return self._trace_active(frame, event, arg)
            return None

        if self._is_stdlib(frame.f_code.co_filename):
            return None

        if thread_id in self._thread_states:
            return self._trace_active(frame, event, arg)

        if self._should_activate(frame, thread_id, thread_name):
            return self._trace_active(frame, event, arg)

        return None

    def _trace_active(self, frame, event: str, arg: Any):
        filename = frame.f_code.co_filename
        if event == "call" and self._is_stdlib(filename):
            return None

        thread_id = threading.get_ident()
        thread_name = threading.current_thread().name

        with self._lock:
            state = self._ensure_thread_state(thread_id, thread_name)
            if len(state.stack) > self.max_depth:
                return None

            function_name = frame.f_code.co_name
            qualname = self._qualified_name(frame)
            lineno = frame.f_lineno
            caller = state.stack[-1] if state.stack else None
            depth = len(state.stack)

            event_matches = self._event_matches_scope_filters(
                filename=filename,
                lineno=lineno,
                thread_id=thread_id,
                thread_name=thread_name,
            )

            func_key = f"{thread_id}:{qualname}"
            event_data: dict[str, Any] | None = None
            current_locals: dict[str, tuple[str, str]] = {}
            delta: dict[str, dict[str, str]] = {}

            if event == "call":
                current_locals = self._extract_locals(frame)
                state.active_frames += 1
                state.stack.append(function_name)
                if event_matches:
                    event_data = {
                        "id": self._next_event_id(),
                        "type": "call",
                        "timestamp": time.time(),
                        "thread_id": thread_id,
                        "thread_name": thread_name,
                        "file": filename,
                        "function": function_name,
                        "line": lineno,
                        "source": self._get_source_line(filename, lineno),
                        "depth": depth,
                        "arguments": self._extract_arguments(frame),
                        "locals": current_locals,
                    }
                    if caller:
                        event_data["caller"] = caller
            elif event == "line":
                current_locals = self._extract_locals(frame)
                delta = self._compute_delta(state.prev_locals, func_key, current_locals)
                if event_matches:
                    event_data = {
                        "id": self._next_event_id(),
                        "type": "line",
                        "timestamp": time.time(),
                        "thread_id": thread_id,
                        "thread_name": thread_name,
                        "file": filename,
                        "function": function_name,
                        "line": lineno,
                        "source": self._get_source_line(filename, lineno),
                        "depth": depth,
                    }
                    if caller:
                        event_data["caller"] = caller
                    if delta:
                        event_data["delta"] = delta
                    if self.detail_level == "detailed" and current_locals:
                        event_data["locals"] = current_locals
            elif event == "return":
                current_locals = self._extract_locals(frame)
                state.prev_locals.pop(func_key, None)
                if event_matches:
                    event_data = {
                        "id": self._next_event_id(),
                        "type": "return",
                        "timestamp": time.time(),
                        "thread_id": thread_id,
                        "thread_name": thread_name,
                        "file": filename,
                        "function": function_name,
                        "line": lineno,
                        "source": self._get_source_line(filename, lineno),
                        "depth": max(depth - 1, 0),
                        "return_value": self._format_value(arg),
                        "locals": current_locals,
                    }
                    if caller:
                        event_data["caller"] = caller
                if state.stack:
                    state.stack.pop()
                state.active_frames = max(state.active_frames - 1, 0)
            elif event == "exception":
                exc_type, exc_value, exc_tb = arg
                if event_matches:
                    tb_lines = _traceback_module.format_tb(exc_tb) if exc_tb else []
                    event_data = {
                        "id": self._next_event_id(),
                        "type": "exception",
                        "timestamp": time.time(),
                        "thread_id": thread_id,
                        "thread_name": thread_name,
                        "file": filename,
                        "function": function_name,
                        "line": lineno,
                        "source": self._get_source_line(filename, lineno),
                        "depth": depth,
                        "exception": {
                            "type": getattr(exc_type, "__name__", str(exc_type)),
                            "value": str(exc_value),
                            "traceback": "".join(tb_lines),
                        },
                    }
                    if caller:
                        event_data["caller"] = caller
            else:
                return self._trace_active

            if event_data is not None:
                self.events.append(event_data)

            if state.active_frames == 0:
                self._thread_states.pop(thread_id, None)

        return self._trace_active

    def _next_event_id(self) -> int:
        self.event_id += 1
        return self.event_id

    def start(self):
        if self.enabled:
            return
        self.enabled = True
        self.start_time = time.time()
        self.metadata["start_time"] = datetime.now().astimezone().isoformat()
        sys.settrace(self._dispatch_trace)
        threading.settrace(self._dispatch_trace)

    def stop(self):
        if not self.enabled:
            return
        sys.settrace(None)
        threading.settrace(None)
        self.enabled = False
        self.end_time = time.time()
        self.metadata["end_time"] = datetime.now().astimezone().isoformat()

    @contextmanager
    def activate_for_current_thread(self):
        started_here = False
        if not self.enabled:
            self.start()
            started_here = True

        thread_id = threading.get_ident()
        self._forced_threads[thread_id] = self._forced_threads.get(thread_id, 0) + 1
        previous_trace = sys.gettrace()
        sys.settrace(self._dispatch_trace)
        try:
            yield self
        finally:
            remaining = self._forced_threads.get(thread_id, 1) - 1
            if remaining > 0:
                self._forced_threads[thread_id] = remaining
            else:
                self._forced_threads.pop(thread_id, None)
            sys.settrace(previous_trace if previous_trace is not None else self._dispatch_trace)
            if started_here:
                self.stop()

    def _event_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.events:
            counts[event["type"]] = counts.get(event["type"], 0) + 1
        return counts

    def _build_xml_tree(self) -> ET.Element:
        root = ET.Element("trace")
        root.set("schema_version", self.schema_version)

        metadata_elem = ET.SubElement(root, "metadata")
        for key in ("python_version", "platform", "start_time", "end_time"):
            ET.SubElement(metadata_elem, key).text = str(self.metadata.get(key))
        ET.SubElement(metadata_elem, "schema_version").text = self.schema_version

        stats_elem = ET.SubElement(metadata_elem, "statistics")
        ET.SubElement(stats_elem, "total_events").text = str(len(self.events))
        duration = 0.0
        if self.start_time is not None and self.end_time is not None:
            duration = self.end_time - self.start_time
        ET.SubElement(stats_elem, "total_duration").text = f"{duration:.6f}"
        counts = self._event_type_counts()
        for event_name in ("call", "line", "return", "exception"):
            if event_name in counts:
                ET.SubElement(stats_elem, f"{event_name}_count").text = str(counts[event_name])

        # v2.2: Write instrumented targets to metadata
        if self.schema_version >= "2.2" and (
            self.manifest.functions or self.manifest.files
        ):
            targets_elem = ET.SubElement(metadata_elem, "targets")
            for fn in sorted(self.manifest.functions):
                t = ET.SubElement(targets_elem, "target")
                t.set("type", "function")
                t.set("name", fn)
            for f in sorted(self.manifest.files):
                t = ET.SubElement(targets_elem, "target")
                t.set("type", "file")
                t.set("name", f)

        events_elem = ET.SubElement(root, "events")
        if self.schema_version.startswith("2."):
            self._append_structured_to_xml(events_elem, self._build_structured_events())
        else:
            for event in self.events:
                self._append_event_xml(events_elem, event, in_scope=False)
        return root

    def _build_structured_events(self) -> list[dict[str, Any]]:
        if not self.enable_threading:
            return self._build_scope_tree(self.events)

        events_by_thread: dict[int, list[dict[str, Any]]] = {}
        thread_names: dict[int, str] = {}
        for event in self.events:
            thread_id = event["thread_id"]
            events_by_thread.setdefault(thread_id, []).append(event)
            thread_names[thread_id] = event.get("thread_name", "")

        nodes: list[dict[str, Any]] = []
        for thread_id, thread_events in events_by_thread.items():
            nodes.append(
                {
                    "type": "thread",
                    "id": str(thread_id),
                    "name": thread_names.get(thread_id, ""),
                    "children": self._build_scope_tree(thread_events),
                }
            )
        return nodes

    def _build_scope_tree(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        index = 0
        while index < len(events):
            event = events[index]
            if event["type"] == "call":
                scope_events, end_idx = self._collect_scope_events(events, index)
                closing_event = events[end_idx] if end_idx < len(events) else None
                start_ts: Optional[float] = event.get("timestamp")
                end_ts: Optional[float] = None
                scope_node = {
                    "type": "scope",
                    "function": event["function"],
                    "file": event["file"],
                    "call_line": event["line"],
                    "depth": event.get("depth", 0),
                    "arguments": event.get("arguments", {}),
                    "children": self._build_scope_tree(scope_events),
                    "return_value": None,
                    "exception": None,
                    # v2.2: function-level timing
                    "start_time": start_ts,
                    "end_time": None,
                    "duration": None,
                }
                if closing_event is not None:
                    end_ts = closing_event.get("timestamp")
                    if closing_event["type"] == "return":
                        scope_node["return_value"] = closing_event.get("return_value")
                    elif closing_event["type"] == "exception":
                        scope_node["exception"] = closing_event.get("exception")
                if start_ts is not None and end_ts is not None:
                    scope_node["end_time"] = end_ts
                    scope_node["duration"] = end_ts - start_ts
                nodes.append(scope_node)
                index = end_idx + 1
            else:
                nodes.append({"type": "event", "data": event})
                index += 1
        return self._compact_loops(nodes)

    def _collect_scope_events(
        self, events: list[dict[str, Any]], call_index: int
    ) -> tuple[list[dict[str, Any]], int]:
        start_event = events[call_index]
        depth = 0
        inner_events: list[dict[str, Any]] = []
        index = call_index + 1
        while index < len(events):
            event = events[index]
            same_scope = (
                event["function"] == start_event["function"]
                and event["file"] == start_event["file"]
                and event["thread_id"] == start_event["thread_id"]
            )
            if event["type"] == "call" and same_scope:
                depth += 1
                inner_events.append(event)
            elif event["type"] in {"return", "exception"} and same_scope:
                if depth == 0:
                    return inner_events, index
                depth -= 1
                inner_events.append(event)
            else:
                inner_events.append(event)
            index += 1
        return inner_events, index

    def _compact_loops(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(nodes) < 2:
            return nodes

        compacted: list[dict[str, Any]] = []
        index = 0
        while index < len(nodes):
            node = nodes[index]
            if node["type"] != "event" or node["data"]["type"] != "line":
                compacted.append(node)
                index += 1
                continue

            source = node["data"].get("source", "").lstrip()
            if not (source.startswith("for ") or source.startswith("while ")):
                compacted.append(node)
                index += 1
                continue

            loop_key = (
                node["data"]["line"],
                node["data"]["file"],
                node["data"]["function"],
            )
            header_positions = [index]
            for offset in range(index + 1, len(nodes)):
                sibling = nodes[offset]
                if (
                    sibling["type"] == "event"
                    and sibling["data"]["type"] == "line"
                    and (
                        sibling["data"]["line"],
                        sibling["data"]["file"],
                        sibling["data"]["function"],
                    )
                    == loop_key
                ):
                    header_positions.append(offset)

            if len(header_positions) < self._loop_compact_threshold + 1:
                compacted.append(node)
                index += 1
                continue

            iteration_events: list[list[dict[str, Any]]] = []
            for pos in range(len(header_positions) - 1):
                start_pos = header_positions[pos]
                end_pos = header_positions[pos + 1]
                iteration_events.append(nodes[start_pos + 1 : end_pos])

            intermediate_headers = [nodes[pos] for pos in header_positions[1:]]
            compacted.append(
                {
                    "type": "loop",
                    "line": node["data"]["line"],
                    "source": node["data"].get("source", ""),
                    "loop_type": "for" if source.startswith("for ") else "while",
                    "iterations": len(iteration_events),
                    "iteration_events": iteration_events,
                    "summary": self._build_loop_summary(iteration_events, intermediate_headers),
                }
            )
            index = header_positions[-1] + 1

        return compacted

    @staticmethod
    def _build_loop_summary(
        iteration_events: list[list[dict[str, Any]]],
        header_nodes: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, dict[str, str | int]]:
        summary: dict[str, dict[str, str | int]] = {}

        def absorb(delta: dict[str, dict[str, str]]) -> None:
            for name, change in delta.items():
                new_value = change.get("new", change.get("old", ""))
                old_value = change.get("old", "")
                if name not in summary:
                    summary[name] = {
                        "initial": old_value if change["action"] in {"changed", "removed"} else new_value,
                        "final": new_value,
                        "change_count": 1,
                    }
                else:
                    summary[name]["final"] = new_value
                    summary[name]["change_count"] = int(summary[name]["change_count"]) + 1

        for iteration in iteration_events:
            for node in iteration:
                if node.get("type") == "event":
                    absorb(node["data"].get("delta", {}))

        for node in header_nodes or []:
            if node.get("type") == "event":
                absorb(node["data"].get("delta", {}))

        return summary

    def _append_structured_to_xml(
        self, parent: ET.Element, nodes: list[dict[str, Any]], in_scope: bool = False
    ) -> None:
        for node in nodes:
            node_type = node["type"]
            if node_type == "event":
                self._append_event_xml(parent, node["data"], in_scope=in_scope)
            elif node_type == "scope":
                self._append_scope_xml(parent, node)
            elif node_type == "loop":
                self._append_loop_xml(parent, node)
            elif node_type == "thread":
                self._append_thread_xml(parent, node)

    def _append_event_xml(
        self, parent: ET.Element, event: dict[str, Any], in_scope: bool = False
    ) -> ET.Element:
        element = ET.SubElement(parent, "event")
        element.set("id", str(event["id"]))
        element.set("type", event["type"])
        element.set("timestamp", f"{event['timestamp']:.6f}")
        if "depth" in event and not in_scope:
            element.set("depth", str(event["depth"]))

        emit_context = not in_scope or not self.schema_version.startswith("2.")
        if emit_context or self.enable_threading:
            ET.SubElement(element, "thread_id").text = str(event["thread_id"])
        if emit_context:
            ET.SubElement(element, "file").text = event["file"]
            ET.SubElement(element, "function").text = event["function"]

        ET.SubElement(element, "line").text = str(event["line"])
        if event.get("source"):
            ET.SubElement(element, "source").text = event["source"]
        if event.get("caller") and emit_context:
            ET.SubElement(element, "caller").text = event["caller"]

        if event.get("delta"):
            delta_elem = ET.SubElement(element, "delta")
            for variable, change in event["delta"].items():
                change_elem = ET.SubElement(delta_elem, "change")
                change_elem.set("name", variable)
                change_elem.set("action", change["action"])
                change_elem.set("type", change.get("type", "unknown"))
                if "old" in change:
                    ET.SubElement(change_elem, "old").text = change["old"]
                if "new" in change:
                    ET.SubElement(change_elem, "new").text = change["new"]

        if event.get("arguments"):
            args_elem = ET.SubElement(element, "arguments")
            for arg_name, (arg_value, arg_type) in event["arguments"].items():
                arg_elem = ET.SubElement(args_elem, "arg")
                arg_elem.set("name", arg_name)
                arg_elem.set("type", arg_type)
                arg_elem.text = arg_value

        if event.get("locals"):
            locals_elem = ET.SubElement(element, "locals")
            for name, (value, value_type) in event["locals"].items():
                var_elem = ET.SubElement(locals_elem, "var")
                var_elem.set("name", name)
                var_elem.set("type", value_type)
                var_elem.text = value

        if event.get("return_value") is not None:
            return_value, return_type = event["return_value"]
            ret_elem = ET.SubElement(element, "return_value")
            ret_elem.set("name", "return")
            ret_elem.set("type", return_type)
            ret_elem.text = return_value

        if event.get("exception"):
            exc_elem = ET.SubElement(element, "exception")
            ET.SubElement(exc_elem, "type").text = event["exception"]["type"]
            ET.SubElement(exc_elem, "value").text = event["exception"]["value"]
            # v2.2: traceback
            tb = event["exception"].get("traceback", "")
            if tb and self.schema_version >= "2.2":
                ET.SubElement(exc_elem, "traceback").text = tb

        return element

    def _append_scope_xml(self, parent: ET.Element, node: dict[str, Any]) -> ET.Element:
        element = ET.SubElement(parent, "scope")
        element.set("function", node["function"])
        element.set("file", node["file"])
        element.set("call_line", str(node["call_line"]))
        element.set("depth", str(node["depth"]))
        # v2.2: function-level timing
        if self.schema_version >= "2.2":
            if node.get("start_time") is not None:
                element.set("start_time", f"{node['start_time']:.6f}")
            if node.get("end_time") is not None:
                element.set("end_time", f"{node['end_time']:.6f}")
            if node.get("duration") is not None:
                element.set("duration", f"{node['duration']:.6f}")

        if node.get("arguments"):
            args_elem = ET.SubElement(element, "arguments")
            for name, (value, value_type) in node["arguments"].items():
                arg_elem = ET.SubElement(args_elem, "arg")
                arg_elem.set("name", name)
                arg_elem.set("type", value_type)
                arg_elem.text = value

        self._append_structured_to_xml(element, node.get("children", []), in_scope=True)

        if node.get("return_value") is not None:
            return_value, return_type = node["return_value"]
            ret_elem = ET.SubElement(element, "return_value")
            ret_elem.set("name", "return")
            ret_elem.set("type", return_type)
            ret_elem.text = return_value

        if node.get("exception") is not None:
            exc_elem = ET.SubElement(element, "exception")
            ET.SubElement(exc_elem, "type").text = node["exception"]["type"]
            ET.SubElement(exc_elem, "value").text = node["exception"]["value"]
            # v2.2: traceback
            tb = node["exception"].get("traceback", "")
            if tb and self.schema_version >= "2.2":
                ET.SubElement(exc_elem, "traceback").text = tb

        return element

    def _append_loop_xml(self, parent: ET.Element, node: dict[str, Any]) -> ET.Element:
        element = ET.SubElement(parent, "loop")
        element.set("line", str(node["line"]))
        element.set("source", node["source"])
        element.set("iterations", str(node["iterations"]))
        element.set("type", node["loop_type"])

        iterations = node["iteration_events"]
        if self.max_iterations is not None and len(iterations) > self.max_iterations:
            head_count = (self.max_iterations + 1) // 2
            tail_count = self.max_iterations - head_count
            skipped = len(iterations) - head_count - tail_count
            selected_indices = list(range(head_count)) + list(
                range(len(iterations) - tail_count, len(iterations))
            )
            if skipped > 0:
                element.set("truncated_iterations", str(skipped))
        else:
            selected_indices = list(range(len(iterations)))

        for index in selected_indices:
            iter_elem = ET.SubElement(element, "iteration")
            iter_elem.set("index", str(index))
            self._append_structured_to_xml(iter_elem, iterations[index], in_scope=True)

        if node.get("summary"):
            summary_elem = ET.SubElement(element, "summary")
            for name, info in node["summary"].items():
                variable_elem = ET.SubElement(summary_elem, "variable_changes")
                variable_elem.set("name", name)
                if "initial" in info:
                    variable_elem.set("initial", str(info["initial"]))
                if "final" in info:
                    variable_elem.set("final", str(info["final"]))
                if "change_count" in info:
                    variable_elem.set("change_count", str(info["change_count"]))

        return element

    def _append_thread_xml(self, parent: ET.Element, node: dict[str, Any]) -> ET.Element:
        element = ET.SubElement(parent, "thread")
        element.set("id", node["id"])
        if node.get("name"):
            element.set("name", node["name"])
        self._append_structured_to_xml(element, node.get("children", []), in_scope=False)
        return element

    def save_to_xml(self, pretty_print: bool = True) -> None:
        root = self._build_xml_tree()
        output_path = Path(self.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        xml_string = ET.tostring(root, encoding="unicode")
        if pretty_print:
            xml_string = minidom.parseString(xml_string).toprettyxml(indent="  ")
            xml_string = _apply_cdata(xml_string)
        else:
            xml_string = '<?xml version="1.0" ?>\n' + xml_string
        output_path.write_text(xml_string, encoding="utf-8")

    def _build_json_events(self) -> list[dict[str, Any]]:
        built: list[dict[str, Any]] = []
        for event in self.events:
            payload = {
                "seq": event["id"],
                "etype": event["type"],
                "timestamp": event["timestamp"],
                "depth": event.get("depth", 0),
                "thread_id": event["thread_id"],
                "thread_name": event.get("thread_name"),
                "frame": {
                    "func": event["function"],
                    "line": event["line"],
                    "file": event["file"],
                },
            }
            if event.get("source"):
                payload["source"] = event["source"]
            if event.get("arguments"):
                payload["args"] = {
                    name: {"value": value[0], "type": value[1]}
                    for name, value in event["arguments"].items()
                }
            if event.get("locals"):
                payload["locals"] = {
                    name: {"value": value[0], "type": value[1]}
                    for name, value in event["locals"].items()
                }
            if event.get("delta"):
                payload["delta"] = event["delta"]
            if event.get("return_value") is not None:
                payload["return_value"] = {
                    "value": event["return_value"][0],
                    "type": event["return_value"][1],
                }
            if event.get("exception"):
                payload["exception"] = event["exception"]
            built.append(payload)
        return built

    def save_to_json(self, output_file: Optional[str] = None) -> None:
        output_path = Path(output_file or self.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": {
                **self.metadata,
                "schema_version": self.schema_version,
                "statistics": {
                    "total_events": len(self.events),
                    "total_duration": (
                        (self.end_time or time.time()) - (self.start_time or time.time())
                    ),
                },
            },
            "events": self._build_json_events(),
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def save_to_jsonl(self, output_file: Optional[str] = None) -> None:
        output_path = Path(output_file or self.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = "\n".join(json.dumps(item) for item in self._build_json_events())
        output_path.write_text(lines + ("\n" if lines else ""), encoding="utf-8")

    def save(self, format: Optional[str] = None) -> None:
        selected_format = (format or self.output_format).lower()
        if selected_format == "xml":
            self.save_to_xml()
        elif selected_format == "json":
            self.save_to_json()
        elif selected_format == "jsonl":
            self.save_to_jsonl()
        else:
            raise ValueError(f"Unsupported format: {selected_format}")

    def print_summary(self) -> None:
        duration = 0.0
        if self.start_time is not None and self.end_time is not None:
            duration = self.end_time - self.start_time
        print("\n" + "=" * 60)
        print("TRACE SUMMARY")
        print("=" * 60)
        print(f"Total Events: {len(self.events)}")
        print(f"Duration: {duration:.4f} seconds")
        print(f"Output File: {self.output_file}")
        print("Event Types:")
        for event_name, count in sorted(self._event_type_counts().items()):
            print(f"  - {event_name}: {count}")
        print("=" * 60 + "\n")


class TraceContext:
    def __init__(
        self,
        output_file: Optional[str] = None,
        recorder: Optional[TraceRecorder] = None,
        **kwargs,
    ):
        if recorder is not None and (output_file is not None or kwargs):
            raise ValueError("Pass either recorder or recorder constructor arguments, not both.")
        self.recorder = recorder or TraceRecorder(output_file=output_file, **kwargs)

    def __enter__(self) -> TraceRecorder:
        self.recorder.start()
        return self.recorder

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.recorder.stop()
        self.recorder.save()
        self.recorder.print_summary()
        return False


def trace_function(output_file: Optional[str] = None, **kwargs):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **inner_kwargs):
            target_functions = list(kwargs.get("target_functions", []) or [])
            candidates = [func.__name__, getattr(func, "__qualname__", func.__name__)]
            module_name = getattr(func, "__module__", "")
            if module_name:
                candidates.extend(
                    [
                        f"{module_name}.{func.__name__}",
                        f"{module_name}.{getattr(func, '__qualname__', func.__name__)}",
                    ]
                )
            for candidate in candidates:
                if candidate not in target_functions:
                    target_functions.append(candidate)

            context_kwargs = dict(kwargs)
            context_kwargs["target_functions"] = target_functions
            with TraceContext(output_file=output_file, **context_kwargs):
                return func(*args, **inner_kwargs)

        return wrapper

    return decorator
