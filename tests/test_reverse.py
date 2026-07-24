"""Reverse execution / state rewind tests (Stage 3)."""

import pytest

from focustracer import TraceContext
from focustracer.core.loader import TraceLoader
from focustracer.core.reverse import (
    Reconstructor,
    reverse_trace,
    result_to_dict,
    state_diff,
)


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


def _recon(out):
    return Reconstructor(TraceLoader().load(out))


# ---------------------------------------------------------------------------


def test_state_at_exception(tmp_path):
    out = _trace(tmp_path, exc_worker,
                 ["exc_divide", "exc_compute", "exc_worker"], catch=ZeroDivisionError)
    recon = _recon(out)
    m = recon.exception_moment()
    assert m is not None
    assert m.function == "exc_divide"
    assert m.source == "return a / b"
    assert m.state["a"][0] == "10"
    assert m.state["b"][0] == "0"  # the fault, recovered from the trace


def test_intra_frame_state_rewinds_across_iterations(tmp_path):
    """total's pre-line value at each `total += v * 2` must rewind 0, 2, 6."""
    out = _trace(tmp_path, accumulate, ["accumulate"])
    recon = _recon(out)
    accum = [m for m in recon.moments if m.source == "total += v * 2"]
    totals = [m.state["total"][0] for m in accum]
    assert totals == ["0", "2", "6"]


def test_reverse_trace_at_line_target(tmp_path):
    out = _trace(tmp_path, accumulate, ["accumulate"])
    recon = _recon(out)
    ret = next(m for m in recon.moments if m.source == "return total")

    result = reverse_trace(out, at_line=ret.line, step_back=3)
    assert result.target.state["total"][0] == "12"
    assert len(result.timeline) == 3


def test_reverse_trace_at_event_target(tmp_path):
    out = _trace(tmp_path, accumulate, ["accumulate"])
    recon = _recon(out)
    first = recon.moments[0]

    result = reverse_trace(out, at_event=first.event_id)
    assert result.target.event_id == first.event_id


def test_state_diff_reports_undo(tmp_path):
    out = _trace(tmp_path, accumulate, ["accumulate"])
    recon = _recon(out)
    accum = [m for m in recon.moments if m.source == "total += v * 2"]
    # between the first two iterations total goes 0 -> 2
    diffs = dict((n, (ev, lv)) for n, ev, lv in state_diff(accum[0], accum[1]))
    assert diffs["total"] == ("0", "2")


def test_no_exception_raises(tmp_path):
    out = _trace(tmp_path, accumulate, ["accumulate"])
    with pytest.raises(ValueError):
        reverse_trace(out, at_exception=True)


def test_result_to_dict_structure(tmp_path):
    out = _trace(tmp_path, exc_worker,
                 ["exc_divide", "exc_compute", "exc_worker"], catch=ZeroDivisionError)
    result = reverse_trace(out, at_exception=True, step_back=3)
    d = result_to_dict(result)
    assert d["criterion"] == "exception"
    assert d["target"]["state"]["b"]["value"] == "0"
    assert isinstance(d["timeline"], list) and d["timeline"]
    # timeline is newest-first; step 0 is the target
    assert d["timeline"][0]["step"] == 0
