"""Trace alignment tests (FR-KIO2-03) — distance + alignment across runs."""

import pytest

from focustracer import TraceContext
from focustracer.core.align import (
    AlignedPair,
    TraceSet,
    align_many,
    align_traces,
    trace_distance,
)


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


# ── multi-trace navigation (FR-KIO2-03 Objective: one session, many traces) ──


def scale(n, factor):
    total = 0
    for i in range(n):
        total += i * factor
    return total


def test_aligned_pair_steps_on_a_and_follows_b(tmp_path):
    """Same control flow, different values: fully aligned, states diverge."""
    a = _trace(tmp_path, "a", lambda: scale(4, 1), ["scale"])
    b = _trace(tmp_path, "b", lambda: scale(4, 10), ["scale"])
    pair = AlignedPair(a, b)
    assert pair.alignment.distance == 0        # identical statement sequences
    assert pair.alignment.gaps == 0

    pair.seek(seq=0)
    pair.step("into")
    pair.step("into")
    assert pair.aligned_index() == pair.a.cursor       # 1:1 alignment
    assert pair.aligned_moment().line == pair.a.current.line

    # Walk forward until the accumulator has been touched, then compare values.
    deltas = []
    while pair.a.can_forward:
        pair.step("into")
        deltas.extend(d["name"] for d in pair.state_delta())
    assert "factor" in deltas       # 1 vs 10 — the input that differs
    assert "total" in deltas        # and the value it propagates into


def test_state_delta_empty_for_identical_runs(tmp_path):
    a = _trace(tmp_path, "a", lambda: loop_n(3), ["loop_n"])
    b = _trace(tmp_path, "b", lambda: loop_n(3), ["loop_n"])
    pair = AlignedPair(a, b)
    while pair.a.can_forward:
        assert pair.state_delta() == []
        pair.step("into")


def test_aligned_pair_to_dict_shape(tmp_path):
    a = _trace(tmp_path, "a", lambda: scale(3, 1), ["scale"])
    b = _trace(tmp_path, "b", lambda: scale(3, 2), ["scale"])
    pair = AlignedPair(a, b)
    pair.seek(seq=2)
    view = pair.to_dict(window=2)
    assert view["aligned"] is True
    assert view["a_seq"] == 2 and view["b_seq"] == 2
    assert view["a"]["current"]["line"] == view["b"]["current"]["line"]
    assert "pairs" not in view["alignment"]        # summary only, no huge pair list
    assert pair.b.cursor == 0                      # to_dict must not move B's cursor


def test_divergences_collapse_gap_runs(tmp_path):
    a = _trace(tmp_path, "a", lambda: loop_n(2), ["loop_n"])
    b = _trace(tmp_path, "b", lambda: loop_n(6), ["loop_n"])
    al = align_traces(a, b)
    divs = al.divergences()
    assert divs                                    # the extra iterations
    assert sum(d.length for d in divs) == al.gaps  # every gap lands in exactly one run
    assert all(d.side in ("a", "b") for d in divs)
    assert all(d.end > d.start for d in divs)


# ── trace-set curation (FR-KIO2-03 Input: "a set of execution traces") ───────


def test_trace_set_matrix_is_symmetric_with_zero_diagonal(tmp_path):
    paths = [
        _trace(tmp_path, "t0", lambda: loop_n(3), ["loop_n"]),
        _trace(tmp_path, "t1", lambda: loop_n(3), ["loop_n"]),
        _trace(tmp_path, "t2", lambda: loop_n(9), ["loop_n"]),
    ]
    ts = TraceSet(paths)
    m = ts.distance_matrix()
    n = len(paths)
    assert all(m[i][i] == 0.0 for i in range(n))          # invariant: d(x, x) = 0
    assert all(m[i][j] == m[j][i] for i in range(n) for j in range(n))
    assert m[0][1] == 0.0                                 # identical runs
    assert m[0][2] > 0.0


def test_trace_set_medoid_and_outlier(tmp_path):
    paths = [
        _trace(tmp_path, "t0", lambda: loop_n(3), ["loop_n"]),
        _trace(tmp_path, "t1", lambda: loop_n(3), ["loop_n"]),
        _trace(tmp_path, "t2", lambda: loop_n(9), ["loop_n"]),
    ]
    ts = TraceSet(paths)
    assert ts.medoid() in (0, 1)      # one of the two representative runs
    assert ts.outlier() == 2          # the divergent one


def test_trace_set_align_to_reference(tmp_path):
    paths = [
        _trace(tmp_path, "t0", lambda: loop_n(3), ["loop_n"]),
        _trace(tmp_path, "t1", lambda: loop_n(5), ["loop_n"]),
        _trace(tmp_path, "t2", lambda: loop_n(9), ["loop_n"]),
    ]
    ts = TraceSet(paths)
    ref = ts.medoid()
    aligned = ts.align_to(ref)
    assert aligned[ref] is None                       # never aligned to itself
    assert all(al is not None for i, al in enumerate(aligned) if i != ref)
    for i, al in enumerate(aligned):
        if al is not None:
            assert al.len_a == len(ts.tokens(ref))    # "reference vs member" order
            assert al.len_b == len(ts.tokens(i))


def test_trace_set_pair_session(tmp_path):
    paths = [
        _trace(tmp_path, "t0", lambda: scale(3, 1), ["scale"]),
        _trace(tmp_path, "t1", lambda: scale(3, 7), ["scale"]),
    ]
    ts = TraceSet(paths)
    pair = ts.pair(0, 1)
    assert pair.alignment.distance == 0
    pair.seek(at_exception=False, seq=1)
    assert pair.aligned_index() == 1


def test_trace_set_rejects_single_trace(tmp_path):
    one = _trace(tmp_path, "only", lambda: loop_n(2), ["loop_n"])
    with pytest.raises(ValueError):
        TraceSet([one])


def test_align_many_summary(tmp_path):
    paths = [
        _trace(tmp_path, "t0", lambda: loop_n(3), ["loop_n"]),
        _trace(tmp_path, "t1", lambda: loop_n(3), ["loop_n"]),
        _trace(tmp_path, "t2", lambda: loop_n(8), ["loop_n"]),
    ]
    s = align_many(paths).to_dict()
    assert s["paths"] == paths
    assert len(s["lengths"]) == 3
    assert s["reference"] in (0, 1) and s["outlier"] == 2
    assert s["mean_distance"] > 0


def build_from(seq):
    """A function whose locals include an object with an address-bearing repr."""
    doubled = [x * 2 for x in seq]     # the comprehension frame carries `.0`
    return sum(doubled)


def test_state_delta_ignores_memory_addresses(tmp_path):
    """Identical runs must show no delta, even for objects without a __repr__.

    Recorded state is a repr; anything rendering as ``<… object at 0x…>`` embeds
    an address that changes every run. Reporting those would flag a difference at
    every aligned point of two identical runs.
    """
    a = _trace(tmp_path, "a", lambda: build_from([1, 2, 3]), ["build_from"])
    b = _trace(tmp_path, "b", lambda: build_from([1, 2, 3]), ["build_from"])
    pair = AlignedPair(a, b)
    while True:
        assert pair.state_delta() == []
        if not pair.a.can_forward:
            break
        pair.step("into")


def test_state_delta_still_reports_real_value_changes(tmp_path):
    a = _trace(tmp_path, "a", lambda: build_from([1, 2, 3]), ["build_from"])
    b = _trace(tmp_path, "b", lambda: build_from([9, 9, 9]), ["build_from"])
    pair = AlignedPair(a, b)
    names = set()
    while pair.a.can_forward:
        pair.step("into")
        names.update(d["name"] for d in pair.state_delta())
    assert "doubled" in names or "seq" in names
