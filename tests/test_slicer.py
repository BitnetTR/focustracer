"""Backward dynamic slicing tests (v2.3)."""

import xml.etree.ElementTree as ET

import pytest

from focustracer import TraceContext
from focustracer.core.loader import TraceLoader
from focustracer.core.slicer import (
    ExecutionModel,
    SliceCriterion,
    build_control_map,
    compute_slice,
    parse_line_def_use,
    slice_trace,
)
from focustracer.validate.validator import validate_xml_against_xsd


# --------------------------------------------------------------------------
# Traced fixtures (module level → stable line numbers, traceable by name)
# --------------------------------------------------------------------------


def clean_target():
    a = 1
    b = 2
    c = a + b
    d = 99  # noqa: F841 — intentionally irrelevant to c
    return c


def control_target(x):
    if x > 0:
        y = 10
    else:
        y = 20
    return y


def exc_divide(a, b):
    return a / b


def exc_compute(values):
    total = 0
    for v in values:
        total += exc_divide(10, v)
    return total


def exc_worker():
    return exc_compute([1, 2, 0])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _trace(tmp_path, func, targets, catch=None):
    out = str(tmp_path / "t.xml")
    with TraceContext(
        output_file=out, output_format="xml", schema_version="2.3",
        detail_level="detailed", target_functions=targets,
    ):
        if catch:
            try:
                func()
            except catch:
                pass
        else:
            func()
    return out


def _model(out):
    return ExecutionModel(TraceLoader().load(out), include_control=True)


def _line_of(model, source_text):
    for st in model.steps:
        if st.source == source_text:
            return st.line
    raise AssertionError(f"no step with source {source_text!r}")


def _sliced_sources(model, result):
    return [model.steps[s].source for s in result.seqs]


# --------------------------------------------------------------------------
# Unit tests — def/use + control map
# --------------------------------------------------------------------------


def test_parse_line_def_use_augassign():
    uses, defs = parse_line_def_use("total += v * 2")
    assert set(uses) == {"total", "v"}
    assert defs == ["total"]


def test_parse_line_def_use_assignment():
    uses, defs = parse_line_def_use("c = a + b")
    assert set(uses) == {"a", "b"}
    assert defs == ["c"]


def test_build_control_map_if():
    src = "def f(x):\n    if x > 0:\n        y = 1\n    return y\n"
    mapping = build_control_map(src)
    assert mapping.get(3) == 2  # `y = 1` controlled by the if on line 2
    assert mapping.get(4) != 2  # `return y` is not inside the if


# --------------------------------------------------------------------------
# Integration — slicing narrows correctly
# --------------------------------------------------------------------------


def test_slice_excludes_irrelevant_statement(tmp_path):
    out = _trace(tmp_path, clean_target, ["clean_target"])
    model = _model(out)
    crit = SliceCriterion(line=_line_of(model, "return c"), var="c")
    result = compute_slice(model, crit)
    sources = _sliced_sources(model, result)

    assert "c = a + b" in sources
    assert "a = 1" in sources
    assert "b = 2" in sources
    assert "d = 99" not in sources  # the whole point of slicing


def test_slice_includes_control_dependency(tmp_path):
    out = _trace(tmp_path, lambda: control_target(5), ["control_target"])
    model = _model(out)
    crit = SliceCriterion(line=_line_of(model, "return y"), var="y")
    result = compute_slice(model, crit)

    # The guarded assignment and its controlling predicate are both in the slice.
    by_source = {model.steps[s].source: result.dependency[s] for s in result.seqs}
    assert "y = 10" in by_source
    assert "if x > 0:" in by_source
    assert by_source["if x > 0:"] == "control"


def test_no_control_flag_drops_control_edges(tmp_path):
    out = _trace(tmp_path, lambda: control_target(5), ["control_target"])
    model = ExecutionModel(TraceLoader().load(out), include_control=False)
    crit = SliceCriterion(line=_line_of(model, "return y"), var="y")
    result = compute_slice(model, crit)
    assert "control" not in result.dependency.values()


def test_exception_slice_finds_root_cause(tmp_path):
    out = _trace(
        tmp_path, exc_worker,
        ["exc_divide", "exc_compute", "exc_worker"], catch=ZeroDivisionError,
    )
    model = _model(out)
    result = compute_slice(model, SliceCriterion(line=0, kind="exception"))
    sources = _sliced_sources(model, result)

    # The failing line is the criterion.
    assert model.steps[result.criterion_seq].source == "return a / b"
    assert result.dependency[result.criterion_seq] == "criterion"
    # The causal chain: the call, the loop, and where [1, 2, 0] entered.
    assert "total += exc_divide(10, v)" in sources
    assert "for v in values:" in sources
    assert "return exc_compute([1, 2, 0])" in sources


def test_sliced_xml_validates_against_v23(tmp_path):
    out = _trace(
        tmp_path, exc_worker,
        ["exc_divide", "exc_compute", "exc_worker"], catch=ZeroDivisionError,
    )
    model, result = slice_trace(out, at_exception=True)
    from focustracer.core.slicer import annotate_trace_with_slice

    sliced = annotate_trace_with_slice(out, model, result, str(tmp_path / "out.sliced.xml"))
    ok, errors = validate_xml_against_xsd(sliced)
    assert ok, f"sliced XML failed v2.3 validation: {errors}"

    root = ET.parse(sliced).getroot()
    slice_elem = root.find("slice")
    assert slice_elem is not None
    assert slice_elem.get("criterion", "").startswith("exception@")
    assert len(slice_elem.findall("node")) >= 3
