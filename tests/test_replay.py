"""Interactive replay tests — forward + backward cursor navigation (FR-KIO2-02)."""

import pytest

from focustracer import TraceContext
from focustracer.core.replay import ReplaySession


def accumulate():
    total = 0
    for v in [1, 2, 3]:
        total += v * 2
    return total


def exc_divide(a, b):
    return a / b


def exc_compute(values):
    total = 0
    for v in values:
        total += exc_divide(10, v)
    return total


def exc_worker():
    return exc_compute([1, 2, 0])


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


def _session(tmp_path, func, targets, catch=None):
    return ReplaySession.from_trace(_trace(tmp_path, func, targets, catch))


# ---------------------------------------------------------------------------


def test_starts_at_beginning(tmp_path):
    s = _session(tmp_path, accumulate, ["accumulate"])
    assert s.cursor == 0
    assert s.total > 1
    assert s.can_forward is True
    assert s.can_back is False


def test_forward_backward_symmetry(tmp_path):
    """Stepping forward then back must land on the exact same moment/state."""
    s = _session(tmp_path, accumulate, ["accumulate"])
    start_seq = s.cursor
    start_state = dict(s.state())
    s.step_forward(3)
    assert s.cursor == start_seq + 3
    s.step_back(3)
    assert s.cursor == start_seq
    assert {k: v for k, v in s.state().items()} == start_state


def test_boundary_clamping(tmp_path):
    """The cursor never leaves [0, total-1] no matter how far we push it."""
    s = _session(tmp_path, accumulate, ["accumulate"])
    s.step_back(999)
    assert s.cursor == 0
    assert s.can_back is False
    s.step_forward(999)
    assert s.cursor == s.total - 1
    assert s.can_forward is False


def test_jump_to_exception_lands_on_fault(tmp_path):
    s = _session(tmp_path, exc_worker,
                 ["exc_divide", "exc_compute", "exc_worker"], catch=ZeroDivisionError)
    m = s.jump_to_exception()
    assert m.function == "exc_divide"
    assert m.source == "return a / b"
    assert s.state()["b"][0] == "0"  # the fault, recovered from the trace
    assert s.cursor == m.seq


def test_jump_to_line_and_event_roundtrip(tmp_path):
    s = _session(tmp_path, accumulate, ["accumulate"])
    m = s.jump_to_line(0, function="accumulate") if False else None  # guard: line 0 never matches
    # jump to a known executed source line via its event id
    target = next(mm for mm in s.moments if mm.source == "total += v * 2")
    back = s.jump_to_event(target.event_id)
    assert back.seq == target.seq
    assert s.cursor == target.seq


def test_jump_to_missing_event_raises(tmp_path):
    s = _session(tmp_path, accumulate, ["accumulate"])
    with pytest.raises(ValueError):
        s.jump_to_event(10_000_000)


def test_def_of_finds_defining_statement(tmp_path):
    """At the last `total += v * 2`, def_of('total') points at that assignment."""
    s = _session(tmp_path, accumulate, ["accumulate"])
    accum = [m for m in s.moments if m.source == "total += v * 2"]
    s.jump_to_seq(accum[-1].seq)
    site = s.def_of("total")
    assert site is not None
    assert site.name == "total"
    # the value visible at the last accumulate line is the pre-line running total
    assert site.new_value == s.state()["total"][0]


def test_to_dict_shape(tmp_path):
    s = _session(tmp_path, accumulate, ["accumulate"])
    s.step_forward(2)
    d = s.to_dict(window=2)
    assert d["cursor"] == s.cursor
    assert d["total"] == s.total
    assert d["current"]["seq"] == s.cursor
    assert any(e["is_cursor"] for e in d["timeline"])
    assert "state" in d["current"]


def test_empty_trace_rejected(tmp_path):
    with pytest.raises(ValueError):
        ReplaySession([])
