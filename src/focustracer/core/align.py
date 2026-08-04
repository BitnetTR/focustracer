"""Trace alignment — compare multiple execution traces of the same program.

FR-KIO2-03. Given two traces of the *same* program run with different inputs or
configurations, this module aligns their executed-statement sequences (a global
sequence alignment à la Needleman-Wunsch, the classic bioinformatics algorithm)
and reports a **distance** (how (dis)similar) plus the **alignment** encoding
(how the two traces line up, including divergences as gaps).

Invariant: the distance between identical traces is 0.

Scope note: the concrete Behaviour/Output/Invariant of FR-KIO2-03 are implemented
here (alignment + distance + multi-trace navigation). The heavier "AI/ML pipeline"
framing in the requirement's *Description* (dataset curation, model training,
MLOps, privacy) is deferred future / cross-partner work, like the FR-KIO2-05
anomaly-ML technique.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from focustracer.core.replay import ReplaySession


def trace_tokens(xml_path: str) -> list[str]:
    """The executed-statement sequence of a trace: ``"function:line"`` per moment."""
    session = ReplaySession.from_trace(xml_path)
    return [f"{m.function}:{m.line}" for m in session.moments]


@dataclass
class Alignment:
    distance: int                     # raw alignment cost (0 = identical)
    normalized_distance: float        # cost / max(len_a, len_b), in [0, 1]
    len_a: int
    len_b: int
    matched: int                      # aligned positions where the statement is equal
    gaps: int                         # insertions/deletions (divergences)
    pairs: list[tuple[Optional[int], Optional[int]]]  # (a_idx|None, b_idx|None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "distance": self.distance,
            "normalized_distance": round(self.normalized_distance, 4),
            "len_a": self.len_a,
            "len_b": self.len_b,
            "matched": self.matched,
            "gaps": self.gaps,
            "pairs": self.pairs,
        }


def align_sequences(
    a: list[str], b: list[str], *, mismatch: int = 1, gap: int = 1
) -> tuple[int, list[tuple[Optional[int], Optional[int]]]]:
    """Needleman-Wunsch global alignment. Returns ``(cost, pairs)``.

    ``pairs`` is the alignment as ``(a_index | None, b_index | None)`` steps:
    a real pair means the two positions align; ``None`` on one side is a gap
    (a statement present in one trace but not the other).
    """
    n, m = len(a), len(b)
    # DP cost matrix
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i * gap
    for j in range(1, m + 1):
        d[0][j] = j * gap
    for i in range(1, n + 1):
        ai = a[i - 1]
        row, prev = d[i], d[i - 1]
        for j in range(1, m + 1):
            sub = 0 if ai == b[j - 1] else mismatch
            row[j] = min(prev[j - 1] + sub, prev[j] + gap, row[j - 1] + gap)

    # Backtrace to recover the alignment
    pairs: list[tuple[Optional[int], Optional[int]]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if a[i - 1] == b[j - 1] else mismatch):
            pairs.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + gap:
            pairs.append((i - 1, None)); i -= 1
        else:
            pairs.append((None, j - 1)); j -= 1
    pairs.reverse()
    return d[n][m], pairs


def align_traces(xml_path_a: str, xml_path_b: str) -> Alignment:
    """Align two trace files and return the distance + alignment encoding."""
    a, b = trace_tokens(xml_path_a), trace_tokens(xml_path_b)
    cost, pairs = align_sequences(a, b)
    matched = sum(1 for i, j in pairs if i is not None and j is not None and a[i] == b[j])
    gaps = sum(1 for i, j in pairs if i is None or j is None)
    denom = max(len(a), len(b)) or 1
    return Alignment(
        distance=cost,
        normalized_distance=cost / denom,
        len_a=len(a),
        len_b=len(b),
        matched=matched,
        gaps=gaps,
        pairs=pairs,
    )


def trace_distance(xml_path_a: str, xml_path_b: str, *, normalized: bool = True) -> float:
    """Distance between two traces. ``0`` iff the executed-statement sequences match."""
    al = align_traces(xml_path_a, xml_path_b)
    return al.normalized_distance if normalized else float(al.distance)


class AlignedPair:
    """Navigate two aligned traces at once — a cursor on trace A maps to trace B.

    Realises "manipulation of multiple execution traces within a single session":
    move the cursor on A, read the aligned state in B (or ``None`` where B diverges).
    """

    def __init__(self, xml_path_a: str, xml_path_b: str):
        self.a = ReplaySession.from_trace(xml_path_a)
        self.b = ReplaySession.from_trace(xml_path_b)
        self.alignment = align_traces(xml_path_a, xml_path_b)
        self._a2b = {i: j for i, j in self.alignment.pairs if i is not None and j is not None}

    def aligned_index(self) -> Optional[int]:
        """The trace-B moment index aligned with A's cursor (``None`` if diverged)."""
        return self._a2b.get(self.a.cursor)

    def aligned_state(self) -> dict[str, Any]:
        """State in both traces at A's cursor; ``b`` is ``None`` where B diverges."""
        bj = self.aligned_index()
        return {
            "a_seq": self.a.cursor,
            "b_seq": bj,
            "aligned": bj is not None,
            "a_state": {k: v[0] for k, v in self.a.state().items()},
            "b_state": (
                {k: v[0] for k, v in self.b.moments[bj].state.items()} if bj is not None else None
            ),
        }
