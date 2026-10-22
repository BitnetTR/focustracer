"""Trace alignment — compare multiple execution traces of the same program.

FR-KIO2-03. Given traces of the *same* program run with different inputs or
configurations, this module aligns their executed-statement sequences (a global
sequence alignment à la Needleman-Wunsch, the classic bioinformatics algorithm)
and reports a **distance** (how (dis)similar) plus the **alignment** encoding
(how the traces line up, including divergences as gaps).

Three layers, matching the three things FR-KIO2-03 asks for:

``align_sequences`` / ``align_traces`` / ``trace_distance``
    *"A measure of the difference between two execution traces"* and *"an
    encoding of how traces can be aligned with each other"* (the Output).

:class:`AlignedPair`
    *"Manipulation of multiple execution traces within a single interactive
    session"* (the Objective) — one movable cursor on trace A that reports the
    aligned position and state in trace B, or ``None`` where B diverges.

:class:`TraceSet`
    *"Lays down foundation to curate sets of execution traces"* (the Objective)
    over the requirement's actual Input, *"a set of execution traces relating to
    a single program"*: N traces, their pairwise distance matrix, the **medoid**
    (the most representative run, used as the alignment reference) and the
    **outlier** (the most divergent run — the natural first suspect when
    debugging). The distance matrix is also the input FR-KIO2-05 needs for
    statistical anomaly detection over a trace set.

Invariant: the distance between identical traces is 0.

Scope note: the concrete Behaviour/Output/Invariant of FR-KIO2-03 are implemented
here (alignment + distance + multi-trace navigation + set curation). The heavier
"AI/ML pipeline" framing in the requirement's *Description* (feature engineering,
model training, MLOps, privacy) is deferred future / cross-partner work, like the
FR-KIO2-05 anomaly-ML technique.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from focustracer.core.replay import ReplaySession
from focustracer.core.reverse import Moment


def trace_tokens(xml_path: str) -> list[str]:
    """The executed-statement sequence of a trace: ``"function:line"`` per moment."""
    session = ReplaySession.from_trace(xml_path)
    return [f"{m.function}:{m.line}" for m in session.moments]


def _tokens(xml_path: str, cache: Optional[dict[str, list[str]]] = None) -> list[str]:
    """``trace_tokens`` with an optional per-caller memo.

    Tokenising means parsing the XML and reconstructing the timeline, so a naive
    N×N distance matrix would re-parse every trace N times. Callers that compare
    the same file repeatedly (``TraceSet``) pass a cache.
    """
    if cache is None:
        return trace_tokens(xml_path)
    if xml_path not in cache:
        cache[xml_path] = trace_tokens(xml_path)
    return cache[xml_path]


_ADDR_RE = re.compile(r"0x[0-9a-fA-F]{4,}")


def _comparable(value: Optional[str]) -> Optional[str]:
    """Normalise a recorded repr so two runs can be compared for *value* equality.

    Recorded state is a string repr. Objects without a custom ``__repr__`` render
    as ``<Foo object at 0x000001B4…>``, and that address differs on every run —
    including two runs of the very same input. Comparing raw reprs would report
    such variables as "changed" at every aligned point (the implicit ``.0``
    iterator of a list comprehension is the common case), burying the real
    differences. Addresses are identity, not value, so they are masked out.
    """
    if value is None:
        return None
    return _ADDR_RE.sub("0xADDR", value)


@dataclass
class Divergence:
    """A contiguous run of gaps — one stretch where the two traces disagree.

    ``side`` is ``"a"`` when the statements exist only in trace A (B skipped
    them), ``"b"`` for the mirror case. Index ranges are half-open.
    """

    side: str            # "a" | "b"
    start: int           # first index on `side`
    end: int             # one past the last index on `side`
    at: Optional[int]    # index on the *other* trace where the divergence sits

    @property
    def length(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "start": self.start,
            "end": self.end,
            "length": self.length,
            "at": self.at,
        }


@dataclass
class Alignment:
    distance: int                     # raw alignment cost (0 = identical)
    normalized_distance: float        # cost / max(len_a, len_b), in [0, 1]
    len_a: int
    len_b: int
    matched: int                      # aligned positions where the statement is equal
    gaps: int                         # insertions/deletions (divergences)
    pairs: list[tuple[Optional[int], Optional[int]]]  # (a_idx|None, b_idx|None)

    def to_dict(self, *, include_pairs: bool = True) -> dict[str, Any]:
        """Serialise. ``include_pairs=False`` omits the (potentially huge) pair list."""
        out: dict[str, Any] = {
            "distance": self.distance,
            "normalized_distance": round(self.normalized_distance, 4),
            "len_a": self.len_a,
            "len_b": self.len_b,
            "matched": self.matched,
            "gaps": self.gaps,
        }
        if include_pairs:
            out["pairs"] = self.pairs
        return out

    def divergences(self) -> list[Divergence]:
        """Collapse the gap steps into contiguous divergence regions.

        The raw ``pairs`` list is per-statement; for a UI (or a report) the
        useful unit is *"trace A ran these 4 extra statements here"*.
        """
        out: list[Divergence] = []
        run_side: Optional[str] = None
        run_start = 0
        run_end = 0
        run_at: Optional[int] = None
        last_a: Optional[int] = None
        last_b: Optional[int] = None

        def flush() -> None:
            nonlocal run_side
            if run_side is not None:
                out.append(Divergence(run_side, run_start, run_end, run_at))
                run_side = None

        for ai, bj in self.pairs:
            if ai is not None and bj is not None:
                flush()
                last_a, last_b = ai, bj
                continue
            side = "a" if ai is not None else "b"
            idx = ai if ai is not None else bj
            assert idx is not None
            if run_side == side and run_end == idx:
                run_end = idx + 1
            else:
                flush()
                run_side, run_start, run_end = side, idx, idx + 1
                run_at = last_b if side == "a" else last_a
        flush()
        return out


def align_sequences(
    a: list[str], b: list[str], *, mismatch: int = 1, gap: int = 1
) -> tuple[int, list[tuple[Optional[int], Optional[int]]]]:
    """Needleman-Wunsch global alignment. Returns ``(cost, pairs)``.

    ``pairs`` is the alignment as ``(a_index | None, b_index | None)`` steps:
    a real pair means the two positions align; ``None`` on one side is a gap
    (a statement present in one trace but not the other).
    """
    if a == b:  # fast path: identical runs align 1:1 at zero cost (the invariant)
        return 0, [(i, i) for i in range(len(a))]

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


def align_token_sequences(a: list[str], b: list[str]) -> Alignment:
    """Align two already-tokenised statement sequences."""
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


def align_traces(
    xml_path_a: str, xml_path_b: str, *, cache: Optional[dict[str, list[str]]] = None
) -> Alignment:
    """Align two trace files and return the distance + alignment encoding."""
    return align_token_sequences(_tokens(xml_path_a, cache), _tokens(xml_path_b, cache))


def trace_distance(xml_path_a: str, xml_path_b: str, *, normalized: bool = True) -> float:
    """Distance between two traces. ``0`` iff the executed-statement sequences match."""
    al = align_traces(xml_path_a, xml_path_b)
    return al.normalized_distance if normalized else float(al.distance)


class AlignedPair:
    """Navigate two aligned traces at once — a cursor on trace A maps to trace B.

    Realises *"manipulation of multiple execution traces within a single
    session"*: move the cursor on A with the ordinary debugger controls
    (``seek`` / ``step``), then read the aligned position and state in B — or
    ``None`` at points where B diverges.
    """

    def __init__(
        self,
        xml_path_a: str,
        xml_path_b: str,
        *,
        alignment: Optional[Alignment] = None,
    ):
        self.path_a = xml_path_a
        self.path_b = xml_path_b
        self.a = ReplaySession.from_trace(xml_path_a)
        self.b = ReplaySession.from_trace(xml_path_b)
        self.alignment = alignment if alignment is not None else align_traces(xml_path_a, xml_path_b)
        self._a2b = {i: j for i, j in self.alignment.pairs if i is not None and j is not None}

    # -- navigation on A (B follows via the alignment) ----------------------

    def seek(
        self,
        *,
        seq: Optional[int] = None,
        event: Optional[int] = None,
        line: Optional[int] = None,
        function: Optional[str] = None,
        at_exception: bool = False,
    ) -> Moment:
        """Position A's cursor. Mirrors the ``replay`` start-point options."""
        if seq is not None:
            return self.a.jump_to_seq(seq)
        if event is not None:
            return self.a.jump_to_event(event)
        if line is not None:
            return self.a.jump_to_line(line, function)
        if at_exception:
            return self.a.jump_to_exception()
        return self.a.current

    def step(self, action: str = "into", back: bool = False) -> Moment:
        """Debugger step on A: ``'into'`` | ``'over'`` | ``'out'``."""
        return self.a.step(action, back=back)

    def step_forward(self, n: int = 1) -> Moment:
        return self.a.step_forward(n)

    def step_back(self, n: int = 1) -> Moment:
        return self.a.step_back(n)

    # -- reading the aligned position --------------------------------------

    def aligned_index(self) -> Optional[int]:
        """The trace-B moment index aligned with A's cursor (``None`` if diverged)."""
        return self._a2b.get(self.a.cursor)

    def aligned_moment(self) -> Optional[Moment]:
        """The trace-B moment aligned with A's cursor (``None`` if diverged)."""
        bj = self.aligned_index()
        return None if bj is None else self.b.moments[bj]

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

    def state_delta(self) -> list[dict[str, Any]]:
        """Variables whose recorded value differs between the two traces here.

        Empty when the traces agree at this point (and always empty for two
        identical runs) — so a non-empty delta is exactly the "these runs
        started behaving differently" signal a developer is looking for.
        """
        bm = self.aligned_moment()
        if bm is None:
            return []
        a_state = self.a.state()
        out: list[dict[str, Any]] = []
        for name in sorted(set(a_state) | set(bm.state)):
            av = a_state.get(name, (None, None))[0]
            bv = bm.state.get(name, (None, None))[0]
            if _comparable(av) != _comparable(bv):
                out.append({"name": name, "a": av, "b": bv})
        return out

    def to_dict(self, window: int = 3) -> dict[str, Any]:
        """Combined cursor view for a UI or CLI: A, the aligned B, and the delta."""
        bj = self.aligned_index()
        b_view: Optional[dict[str, Any]] = None
        if bj is not None:
            keep = self.b.cursor
            self.b.jump_to_seq(bj)
            b_view = self.b.to_dict(window=window)
            self.b.cursor = keep
        return {
            "aligned": bj is not None,
            "a_seq": self.a.cursor,
            "b_seq": bj,
            "a": self.a.to_dict(window=window),
            "b": b_view,
            "delta": self.state_delta(),
            "alignment": self.alignment.to_dict(include_pairs=False),
        }


@dataclass
class TraceSetSummary:
    """Curation view of a set of traces from one program."""

    paths: list[str]
    lengths: list[int]
    matrix: list[list[float]]   # normalized pairwise distances (symmetric, 0 diagonal)
    reference: int              # medoid index — the most representative run
    outlier: int                # index of the run furthest from the reference
    mean_distance: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "paths": self.paths,
            "lengths": self.lengths,
            "matrix": [[round(v, 4) for v in row] for row in self.matrix],
            "reference": self.reference,
            "outlier": self.outlier,
            "mean_distance": round(self.mean_distance, 4),
        }


class TraceSet:
    """A curated set of execution traces from a single program.

    FR-KIO2-03's Input is *"a set of execution traces relating to a single
    program ran with the different inputs and configurations"* — this is the
    primitive for holding that set and reasoning over it as a whole:

    - :meth:`distance_matrix` — every pairwise (normalized) distance;
    - :meth:`medoid` — the most central run, i.e. the natural alignment
      *reference* for the set;
    - :meth:`outlier` — the run furthest from that reference;
    - :meth:`pair` — drop into a two-trace :class:`AlignedPair` session.

    Tokenisation and pairwise alignments are memoised, so building the matrix
    parses each trace once rather than N times.
    """

    def __init__(self, paths: Sequence[str]):
        paths = list(paths)
        if len(paths) < 2:
            raise ValueError("a trace set needs at least 2 traces")
        self.paths = paths
        self._token_cache: dict[str, list[str]] = {}
        self._alignments: dict[tuple[int, int], Alignment] = {}
        self._matrix: Optional[list[list[float]]] = None

    def __len__(self) -> int:
        return len(self.paths)

    def tokens(self, i: int) -> list[str]:
        return _tokens(self.paths[i], self._token_cache)

    def lengths(self) -> list[int]:
        return [len(self.tokens(i)) for i in range(len(self))]

    def alignment(self, i: int, j: int) -> Alignment:
        """Alignment of trace ``i`` against trace ``j`` (memoised, order-normalised)."""
        if i == j:
            toks = self.tokens(i)
            return align_token_sequences(toks, toks)
        key = (i, j) if i < j else (j, i)
        if key not in self._alignments:
            self._alignments[key] = align_token_sequences(
                self.tokens(key[0]), self.tokens(key[1])
            )
        al = self._alignments[key]
        if (i, j) == key:
            return al
        # Swap sides so the caller always gets "i vs j". Cost is symmetric.
        return Alignment(
            distance=al.distance,
            normalized_distance=al.normalized_distance,
            len_a=al.len_b,
            len_b=al.len_a,
            matched=al.matched,
            gaps=al.gaps,
            pairs=[(bj, ai) for ai, bj in al.pairs],
        )

    def distance_matrix(self) -> list[list[float]]:
        """Symmetric matrix of normalized pairwise distances (0 on the diagonal)."""
        if self._matrix is None:
            n = len(self)
            m = [[0.0] * n for _ in range(n)]
            for i in range(n):
                for j in range(i + 1, n):
                    d = self.alignment(i, j).normalized_distance
                    m[i][j] = m[j][i] = d
            self._matrix = m
        return self._matrix

    def medoid(self) -> int:
        """Index of the most representative trace (smallest total distance to the rest)."""
        m = self.distance_matrix()
        return min(range(len(self)), key=lambda i: (sum(m[i]), i))

    def outlier(self, reference: Optional[int] = None) -> int:
        """Index of the trace furthest from ``reference`` (default: the medoid)."""
        ref = self.medoid() if reference is None else reference
        m = self.distance_matrix()
        candidates = [i for i in range(len(self)) if i != ref] or [ref]
        return max(candidates, key=lambda i: (m[ref][i], -i))

    def align_to(self, reference: Optional[int] = None) -> list[Optional[Alignment]]:
        """Align every trace against ``reference`` (default: the medoid).

        The reference's own slot is ``None`` — a trace is not aligned to itself.
        """
        ref = self.medoid() if reference is None else reference
        return [None if i == ref else self.alignment(ref, i) for i in range(len(self))]

    def pair(self, i: int, j: int) -> AlignedPair:
        """An interactive two-trace session over members ``i`` and ``j``."""
        return AlignedPair(self.paths[i], self.paths[j], alignment=self.alignment(i, j))

    def summary(self) -> TraceSetSummary:
        m = self.distance_matrix()
        n = len(self)
        pairs = [m[i][j] for i in range(n) for j in range(i + 1, n)]
        ref = self.medoid()
        return TraceSetSummary(
            paths=list(self.paths),
            lengths=self.lengths(),
            matrix=m,
            reference=ref,
            outlier=self.outlier(ref),
            mean_distance=(sum(pairs) / len(pairs)) if pairs else 0.0,
        )


def align_many(paths: Iterable[str]) -> TraceSetSummary:
    """Convenience: curate a set of traces and return its summary."""
    return TraceSet(list(paths)).summary()
