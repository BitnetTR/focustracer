"""
Trace Loader
============
Kayıtlı XML trace dosyalarını Python veri yapılarına parse eder.
Post-mortem debugging için kullanılır (``focustracer load`` komutu).

Örnek kullanım::

    from focustracer.core.loader import TraceLoader

    loader = TraceLoader()
    doc = loader.load("output/trace.xml")
    print(doc.total_events, doc.total_duration)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TraceDocument:
    """Parse edilmiş bir trace XML dosyasını temsil eder."""

    schema_version: str
    metadata: dict[str, Any]
    nodes: list[dict[str, Any]]
    source_path: str

    # --- convenience properties -------------------------------------------

    @property
    def statistics(self) -> dict[str, Any]:
        return self.metadata.get("statistics", {})

    @property
    def total_events(self) -> int:
        return int(self.statistics.get("total_events", 0))

    @property
    def total_duration(self) -> float:
        return float(self.statistics.get("total_duration", 0.0))

    @property
    def start_time(self) -> Optional[str]:
        return self.metadata.get("start_time")

    @property
    def end_time(self) -> Optional[str]:
        return self.metadata.get("end_time")

    @property
    def targets(self) -> list[dict[str, str]]:
        """v2.2: Hedeflenen fonksiyon/dosya listesi."""
        return self.metadata.get("targets", [])

    # --- counting helpers -------------------------------------------------

    def count_threads(self) -> int:
        return sum(1 for n in self.nodes if n.get("type") == "thread")

    def count_scopes(self) -> int:
        return self._count_type_in(self.nodes, "scope")

    def count_loops(self) -> int:
        return self._count_type_in(self.nodes, "loop")

    def event_type_counts(self) -> dict[str, int]:
        """Tüm ağaçtaki event tiplerini say."""
        counts: dict[str, int] = {}
        self._walk_events(self.nodes, counts)
        return counts

    @classmethod
    def _count_type_in(cls, nodes: list[dict[str, Any]], node_type: str) -> int:
        total = 0
        for node in nodes:
            t = node.get("type")
            if t == node_type:
                total += 1
            if t in ("thread", "scope"):
                total += cls._count_type_in(node.get("children", []), node_type)
            elif t == "loop":
                for iter_obj in node.get("iteration_list", []):
                    total += cls._count_type_in(iter_obj.get("events", []), node_type)
        return total

    @classmethod
    def _walk_events(cls, nodes: list[dict[str, Any]], counts: dict[str, int]) -> None:
        for node in nodes:
            t = node.get("type")
            if t == "event":
                etype = node["data"].get("event_type", "")
                counts[etype] = counts.get(etype, 0) + 1
            elif t in ("thread", "scope"):
                cls._walk_events(node.get("children", []), counts)
            elif t == "loop":
                for iter_obj in node.get("iteration_list", []):
                    cls._walk_events(iter_obj.get("events", []), counts)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class TraceLoader:
    """
    XML trace dosyasını parse ederek :class:`TraceDocument` döndürür.

    v2.x hiyerarşik formatını (thread / scope / loop / event) destekler.
    v1 düz-event formatını da okur.
    """

    def load(self, xml_path: str) -> TraceDocument:
        path = Path(xml_path)
        if not path.exists():
            raise FileNotFoundError(f"Trace file not found: {xml_path}")

        try:
            tree = ET.parse(str(path))
        except ET.ParseError as exc:
            raise ValueError(f"Invalid XML in trace file: {exc}") from exc

        root = tree.getroot()
        schema_version = root.get("schema_version", "1.0")
        metadata = self._parse_metadata(root.find("metadata"))
        events_elem = root.find("events")
        nodes = self._parse_children(events_elem) if events_elem is not None else []

        return TraceDocument(
            schema_version=schema_version,
            metadata=metadata,
            nodes=nodes,
            source_path=str(path.resolve()),
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _parse_metadata(self, elem: Optional[ET.Element]) -> dict[str, Any]:
        if elem is None:
            return {}
        meta: dict[str, Any] = {}
        for child in elem:
            if child.tag == "statistics":
                meta["statistics"] = self._parse_statistics(child)
            elif child.tag == "targets":
                meta["targets"] = self._parse_targets(child)
            elif child.tag == "source_files":
                meta["source_files"] = [
                    sf.get("path", "") for sf in child if sf.tag == "file"
                ]
            else:
                meta[child.tag] = (child.text or "").strip()
        return meta

    def _parse_statistics(self, elem: ET.Element) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        for child in elem:
            text = (child.text or "").strip()
            try:
                stats[child.tag] = float(text) if "." in text else int(text)
            except ValueError:
                stats[child.tag] = text
        return stats

    def _parse_targets(self, elem: ET.Element) -> list[dict[str, str]]:
        return [
            {"type": t.get("type", ""), "name": t.get("name", "")}
            for t in elem
            if t.tag == "target"
        ]

    # ------------------------------------------------------------------
    # Children dispatcher
    # ------------------------------------------------------------------

    def _parse_children(self, parent: ET.Element) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for child in parent:
            if child.tag == "thread":
                nodes.append(self._parse_thread(child))
            elif child.tag == "scope":
                nodes.append(self._parse_scope(child))
            elif child.tag == "loop":
                nodes.append(self._parse_loop(child))
            elif child.tag == "event":
                nodes.append(self._parse_event(child))
        return nodes

    # ------------------------------------------------------------------
    # Thread
    # ------------------------------------------------------------------

    def _parse_thread(self, elem: ET.Element) -> dict[str, Any]:
        return {
            "type": "thread",
            "id": elem.get("id", ""),
            "name": elem.get("name", ""),
            "children": self._parse_children(elem),
        }

    # ------------------------------------------------------------------
    # Scope
    # ------------------------------------------------------------------

    def _parse_scope(self, elem: ET.Element) -> dict[str, Any]:
        node: dict[str, Any] = {
            "type": "scope",
            "function": elem.get("function", ""),
            "file": elem.get("file", ""),
            "call_line": _to_int(elem.get("call_line"), 0),
            "depth": _to_int(elem.get("depth"), 0),
            # v2.2 timing
            "start_time": _to_float(elem.get("start_time")),
            "end_time": _to_float(elem.get("end_time")),
            "duration": _to_float(elem.get("duration")),
            "arguments": {},
            "children": [],
            "return_value": None,
            "exception": None,
        }
        for child in elem:
            if child.tag == "arguments":
                node["arguments"] = self._parse_arguments(child)
            elif child.tag == "return_value":
                node["return_value"] = (
                    (child.text or "").strip(),
                    child.get("type", ""),
                )
            elif child.tag == "exception":
                node["exception"] = self._parse_exception(child)
            elif child.tag in ("scope", "loop", "event"):
                node["children"].append(self._parse_child_node(child))
        return node

    def _parse_child_node(self, elem: ET.Element) -> dict[str, Any]:
        if elem.tag == "scope":
            return self._parse_scope(elem)
        if elem.tag == "loop":
            return self._parse_loop(elem)
        return self._parse_event(elem)

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    def _parse_loop(self, elem: ET.Element) -> dict[str, Any]:
        iteration_list: list[dict[str, Any]] = []
        summary: dict[str, Any] = {}

        for child in elem:
            if child.tag == "iteration":
                iteration_list.append({
                    "index": _to_int(child.get("index"), 0),
                    "start_time": _to_float(child.get("start_time")),
                    "end_time": _to_float(child.get("end_time")),
                    "events": self._parse_children(child),
                })
            elif child.tag == "summary":
                for var_elem in child:
                    if var_elem.tag == "variable_changes":
                        name = var_elem.get("name", "")
                        summary[name] = {
                            "initial": var_elem.get("initial", ""),
                            "final": var_elem.get("final", ""),
                            "change_count": _to_int(var_elem.get("change_count"), 0),
                        }

        return {
            "type": "loop",
            "line": _to_int(elem.get("line"), 0),
            "source": elem.get("source", ""),
            "loop_type": elem.get("type", "for"),
            "iterations": _to_int(elem.get("iterations"), 0),
            "truncated_iterations": _to_int(elem.get("truncated_iterations"), 0),
            "iteration_list": iteration_list,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Event
    # ------------------------------------------------------------------

    def _parse_event(self, elem: ET.Element) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": _to_int(elem.get("id"), 0),
            "event_type": elem.get("type", ""),
            "timestamp": _to_float(elem.get("timestamp")) or 0.0,
            "depth": _to_int(elem.get("depth"), 0),
            "line": 0,
            "source": "",
            "function": "",
            "file": "",
            "thread_id": "",
            "delta": [],
            "arguments": {},
            "locals": {},
            "return_value": None,
            "exception": None,
        }
        for child in elem:
            tag = child.tag
            text = (child.text or "").strip()
            if tag == "line":
                data["line"] = _to_int(text, 0)
            elif tag == "source":
                data["source"] = text
            elif tag == "function":
                data["function"] = text
            elif tag == "file":
                data["file"] = text
            elif tag == "thread_id":
                data["thread_id"] = text
            elif tag == "delta":
                data["delta"] = self._parse_delta(child)
            elif tag == "arguments":
                data["arguments"] = self._parse_arguments(child)
            elif tag == "locals":
                data["locals"] = self._parse_locals(child)
            elif tag == "return_value":
                data["return_value"] = (text, child.get("type", ""))
            elif tag == "exception":
                data["exception"] = self._parse_exception(child)

        return {"type": "event", "data": data}

    # ------------------------------------------------------------------
    # Shared sub-parsers
    # ------------------------------------------------------------------

    def _parse_arguments(self, elem: ET.Element) -> dict[str, tuple[str, str]]:
        return {
            arg.get("name", ""): ((arg.text or "").strip(), arg.get("type", ""))
            for arg in elem
            if arg.tag == "arg"
        }

    def _parse_locals(self, elem: ET.Element) -> dict[str, tuple[str, str]]:
        return {
            var.get("name", ""): ((var.text or "").strip(), var.get("type", ""))
            for var in elem
            if var.tag == "var"
        }

    def _parse_delta(self, elem: ET.Element) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for change in elem:
            if change.tag != "change":
                continue
            c: dict[str, Any] = {
                "name": change.get("name", ""),
                "action": change.get("action", ""),
                "type": change.get("type", ""),
                "old": None,
                "new": None,
            }
            for sub in change:
                if sub.tag == "old":
                    c["old"] = (sub.text or "").strip()
                elif sub.tag == "new":
                    c["new"] = (sub.text or "").strip()
            changes.append(c)
        return changes

    def _parse_exception(self, elem: ET.Element) -> dict[str, str]:
        exc: dict[str, str] = {"type": "", "value": "", "traceback": ""}
        for child in elem:
            if child.tag in exc:
                exc[child.tag] = (child.text or "").strip()
        return exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_int(value: Optional[str], default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
