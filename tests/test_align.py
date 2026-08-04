"""Trace alignment tests (FR-KIO2-03) — distance + alignment across runs."""

from focustracer import TraceContext
from focustracer.core.align import AlignedPair, align_traces, trace_distance


def loop_n(n):
    total = 0
    for i in range(n):
        total += i
    return total


def _trace(tmp_path, name, func, targets):
    out = str(tmp_path / f"{name}.xml")
    with TraceContext(
        output_file=out, output_format="xml", schema_version="2.3",
        detail_level="detailed", target_functions=targets,
    ):
        func()
    return out


def test_identical_traces_have_zero_distance(tmp_path):
    a = _trace(tmp_path, "a", lambda: loop_n(3), ["loop_n"])
    b = _trace(tmp_path, "b", lambda: loop_n(3), ["loop_n"])
    al = align_traces(a, b)
    assert al.distance == 0           # invariant: identical ⇒ distance 0
    assert al.gaps == 0
    assert al.matched == al.len_a == al.len_b
    assert trace_distance(a, b) == 0.0


def test_different_runs_have_positive_distance(tmp_path):
    a = _trace(tmp_path, "a", lambda: loop_n(2), ["loop_n"])
    b = _trace(tmp_path, "b", lambda: loop_n(6), ["loop_n"])
    al = align_traces(a, b)
    assert al.distance > 0
    assert al.gaps > 0                # the extra iterations show up as gaps
    assert 0.0 < trace_distance(a, b) <= 1.0


def test_distance_is_symmetric(tmp_path):
    a = _trace(tmp_path, "a", lambda: loop_n(2), ["loop_n"])
    b = _trace(tmp_path, "b", lambda: loop_n(6), ["loop_n"])
    assert align_traces(a, b).distance == align_traces(b, a).distance


def test_aligned_pair_navigates_two_traces(tmp_path):
    a = _trace(tmp_path, "a", lambda: loop_n(3), ["loop_n"])
    b = _trace(tmp_path, "b", lambda: loop_n(3), ["loop_n"])
    pair = AlignedPair(a, b)
    pair.a.jump_to_seq(0)
    st = pair.aligned_state()
    assert st["aligned"] is True
    assert st["b_seq"] == 0
    assert st["a_state"] == st["b_state"]  # identical runs ⇒ same state at aligned point
