"""v2.3 reads (use-set) capture tests.

Backward dynamic slicing needs, for every executed line, the set of variables it
*reads*. These tests verify that ``detailed`` + schema >= 2.3 records a ``<reads>``
element carrying the read names with their pre-execution values, that the output
validates against the v2.3 XSD, and that the feature is correctly gated.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from focustracer import TraceContext
from focustracer.core.loader import TraceLoader
from focustracer.validate.validator import validate_xml_against_xsd


def _make(tmp_path, func, **ctx):
    out = str(tmp_path / "reads.xml")
    with TraceContext(output_file=str(out), output_format="xml", **ctx):
        func()
    return out


def _reads_in_order(root: ET.Element) -> list[dict[str, str]]:
    """Every event's reads, in document order (repeated loop lines preserved)."""
    result: list[dict[str, str]] = []
    for event in root.iter("event"):
        reads = event.find("reads")
        if reads is None:
            continue
        result.append({r.get("name"): (r.text or "") for r in reads.findall("read")})
    return result


def test_reads_captured_for_augassign_and_use(tmp_path):
    """`total += v * 2` reads total (AugAssign target) and v, with pre-line values."""

    def compute():
        total = 0
        for v in [1, 2, 3]:
            total += v * 2
        return total

    out = _make(tmp_path, compute, schema_version="2.3", detail_level="detailed",
                target_functions=["compute"])
    reads = _reads_in_order(ET.parse(out).getroot())

    # The first event reading both total and v is iteration 1: total=0, v=1.
    aug = [names for names in reads if set(names) >= {"total", "v"}]
    assert aug, f"no line read both total and v; got {reads}"
    assert aug[0]["total"] == "0"
    assert aug[0]["v"] == "1"


def test_reads_validate_against_v23_xsd(tmp_path):
    def compute():
        total = 0
        for v in [1, 2]:
            total += v
        return total

    out = _make(tmp_path, compute, schema_version="2.3", detail_level="detailed",
                target_functions=["compute"])
    ok, errors = validate_xml_against_xsd(out)
    assert ok, f"v2.3 trace failed XSD validation: {errors}"


def test_reads_roundtrip_through_loader(tmp_path):
    def compute():
        total = 0
        for v in [5]:
            total += v
        return total

    out = _make(tmp_path, compute, schema_version="2.3", detail_level="detailed",
                target_functions=["compute"])
    doc = TraceLoader().load(out)

    found = False
    for event in _iter_event_nodes(doc.nodes):
        if event["data"].get("reads"):
            found = True
            for _name, (value, vtype) in event["data"]["reads"].items():
                assert isinstance(value, str) and vtype != ""
    assert found, "loader did not surface any <reads> data"


def test_no_reads_in_normal_detail(tmp_path):
    """reads are a detailed-only feature; normal mode must not emit them."""

    def compute():
        total = 0
        for v in [1, 2]:
            total += v
        return total

    out = _make(tmp_path, compute, schema_version="2.3", detail_level="normal",
                target_functions=["compute"])
    assert ET.parse(out).getroot().find(".//reads") is None


def test_no_reads_below_v23(tmp_path):
    """schema < 2.3 must not emit <reads> even in detailed mode."""

    def compute():
        total = 0
        for v in [1, 2]:
            total += v
        return total

    out = _make(tmp_path, compute, schema_version="2.2", detail_level="detailed",
                target_functions=["compute"])
    assert ET.parse(out).getroot().find(".//reads") is None


def _iter_event_nodes(nodes):
    for node in nodes:
        t = node.get("type")
        if t == "event":
            yield node
        elif t in ("thread", "scope"):
            yield from _iter_event_nodes(node.get("children", []))
        elif t == "loop":
            for it in node.get("iteration_list", []):
                yield from _iter_event_nodes(it.get("events", []))
