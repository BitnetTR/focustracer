"""Reverse execution / state rewind over a FocusTracer trace.

Stage 3 of the KIO2 pipeline. FocusTracer's ``<delta>`` records every variable
change reversibly (added / changed old->new / removed), so the observable
program state at any point is *derivable* from a saved trace — no re-run needed.
This module reconstructs per-frame state at each executed line and lets you
**rewind**: view the state at the crash (or any event/line) and step backward
through the execution, watching values un-wind.

Design note: this is a read/query over an existing trace (like ``load``). It
does NOT modify the trace or the schema — the reconstructed state is derived
data, and the trace stays the immutable record of what happened.

Honest limitation: values are stored as string reprs, so this recovers the
*observable* state (what each variable showed), not live Python objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from focustracer.core.loader import TraceDocument, TraceLoader


@dataclass
class Moment:
    """The observable state of one frame as one line is about to execute."""

    seq: int
    event_id: Optional[int]
    frame_id: int
    function: str
    file: str
    line: int
    source: str
    state: dict[str, tuple[str, str]]  # name -> (value, type)
    depth: int = 0  # call-stack depth (0 = top level); enables step over/into/out


@dataclass
class ReverseResult:
    label: str
    target: Moment
    timeline: list[Moment]  # earlier moments, execution order (target excluded)
    total_moments: int


def _apply_delta(state: dict[str, tuple[str, str]], delta: list[dict[str, Any]]) -> None:
    for change in delta:
        name = change.get("name")
        if not name:
            continue
        action = change.get("action")
        if action in ("added", "changed"):
            state[name] = (change.get("new"), change.get("type", ""))
        elif action == "removed":
            state.pop(name, None)


class Reconstructor:
    """Walks the trace tree, rebuilding per-frame observable state per line."""

    def __init__(self, doc: TraceDocument):
        self.moments: list[Moment] = []
        self._state: dict[int, dict[str, tuple[str, str]]] = {}
        self._frame_counter = 0
        self._exc_seq: Optional[int] = None
        self._exc_depth = -1
        self._walk(doc.nodes, None, "", "", 0)

    def _walk(
        self, nodes: list[dict[str, Any]], frame_id: Optional[int],
        ctx_func: str, ctx_file: str, depth: int,
    ) -> None:
        for node in nodes:
            ntype = node.get("type")
            if ntype == "thread":
                self._walk(node.get("children", []), frame_id, ctx_func, ctx_file, depth)
            elif ntype == "scope":
                fid = self._frame_counter
                self._frame_counter += 1
                func = node.get("function", "")
                file = node.get("file", "")
                # Seed from call arguments; the first line's delta re-adds them.
                self._state[fid] = {
                    n: (v, ty) for n, (v, ty) in node.get("arguments", {}).items()
                }
                self._walk(node.get("children", []), fid, func, file, depth + 1)
                if node.get("exception") is not None and depth >= self._exc_depth:
                    for m in reversed(self.moments):
                        if m.frame_id == fid:
                            self._exc_seq = m.seq
                            self._exc_depth = depth
                            break
            elif ntype == "loop":
                for iteration in node.get("iteration_list", []):
                    self._walk(iteration.get("events", []), frame_id, ctx_func, ctx_file, depth)
            elif ntype == "event":
                data = node["data"]
                if data.get("event_type") != "line":
                    continue
                fid = frame_id if frame_id is not None else -1
                state = self._state.setdefault(fid, {})
                # Baseline: accumulate reversible deltas. Correction: when the
                # line carries a full <locals> snapshot (detailed mode), use it —
                # it is exact and sidesteps the delta offset and loop-header gaps.
                _apply_delta(state, data.get("delta", []))
                snapshot = data.get("locals") or {}
                if snapshot:
                    state.clear()
                    state.update(snapshot)
                self.moments.append(
                    Moment(
                        seq=len(self.moments),
                        event_id=data.get("id"),
                        frame_id=fid,
                        function=data.get("function") or ctx_func,
                        file=data.get("file") or ctx_file,
                        line=data.get("line", 0),
                        source=data.get("source", ""),
                        state=dict(state),
                        depth=depth,
                    )
                )

    # -- target selection --------------------------------------------------

    def exception_moment(self) -> Optional[Moment]:
        if self._exc_seq is None:
            return None
        return self.moments[self._exc_seq]

    def moment_at_event(self, event_id: int) -> Optional[Moment]:
        for m in self.moments:
            if m.event_id == event_id:
                return m
        return None

    def moment_at_line(self, line: int, function: Optional[str] = None) -> Optional[Moment]:
        match: Optional[Moment] = None
        for m in self.moments:
            if m.line != line:
                continue
            if function and m.function != function:
                continue
            match = m  # last occurrence
        return match


def state_diff(
    earlier: Moment, later: Moment
) -> list[tuple[str, Optional[str], Optional[str]]]:
    """Vars that differ from ``earlier`` to ``later`` (same frame only).

    Returns ``(name, earlier_value, later_value)``. Reversing = restoring the
    earlier value; this is what a backward step "un-does".
    """
    if earlier.frame_id != later.frame_id:
        return []
    diffs: list[tuple[str, Optional[str], Optional[str]]] = []
    names = set(earlier.state) | set(later.state)
    for name in sorted(names):
        e = earlier.state.get(name)
        l = later.state.get(name)
        ev = e[0] if e else None
        lv = l[0] if l else None
        if ev != lv:
            diffs.append((name, ev, lv))
    return diffs


def reverse_trace(
    xml_path: str,
    *,
    at_exception: bool = False,
    at_event: Optional[int] = None,
    at_line: Optional[int] = None,
    function: Optional[str] = None,
    step_back: int = 5,
) -> ReverseResult:
    """Reconstruct state at a target point and the ``step_back`` moments before it."""
    doc = TraceLoader().load(xml_path)
    recon = Reconstructor(doc)
    if not recon.moments:
        raise ValueError(
            "trace has no line-level variable data — record with --detail normal or detailed"
        )

    if at_event is not None:
        target = recon.moment_at_event(at_event)
        label = f"event {at_event}"
        if target is None:
            raise ValueError(f"no line event with id {at_event}")
    elif at_line is not None:
        target = recon.moment_at_line(at_line, function)
        label = f"line {at_line}" + (f" in {function}" if function else "")
        if target is None:
            raise ValueError(f"no executed line {at_line}" + (f" in {function}" if function else ""))
    else:  # at_exception (default)
        target = recon.exception_moment()
        if target is None:
            raise ValueError("no exception found in trace")
        label = "exception"

    start = max(0, target.seq - step_back)
    timeline = recon.moments[start:target.seq]
    return ReverseResult(label, target, timeline, len(recon.moments))


def result_to_dict(result: ReverseResult) -> dict[str, Any]:
    """JSON-friendly representation of a reverse result."""

    def moment_dict(m: Moment) -> dict[str, Any]:
        return {
            "event_id": m.event_id,
            "function": m.function,
            "line": m.line,
            "source": m.source,
            "state": {k: {"value": v[0], "type": v[1]} for k, v in m.state.items()},
        }

    steps = []
    ordered = result.timeline + [result.target]
    for i in range(len(ordered) - 1, -1, -1):
        m = ordered[i]
        entry = moment_dict(m)
        entry["step"] = i - (len(ordered) - 1)  # 0 for target, -1, -2, ...
        if i > 0 and ordered[i - 1].frame_id == m.frame_id:
            entry["undo"] = [
                {"name": n, "from": lv, "to": ev}
                for n, ev, lv in state_diff(ordered[i - 1], m)
            ]
        steps.append(entry)
    return {"criterion": result.label, "target": moment_dict(result.target), "timeline": steps}
