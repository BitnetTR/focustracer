"""Interactive replay — forward + backward stepping over a FocusTracer trace.

This is FR-KIO2-02 ("Trace Capture & Replay … forward/backward navigation and
the inspection of state snapshots") realised as a trace-native primitive.

Where ``reverse`` is a one-shot rewind (state at a point + N steps back), a
``ReplaySession`` is a *navigable cursor* over the whole reconstructed timeline:
step forward, step back, jump to an event / line / the crash, read the full
observable state at the cursor, and ask which statement last defined a value
(def-use). It builds on :class:`focustracer.core.reverse.Reconstructor`, which
already rebuilds per-frame observable state for every executed line.

Design note (unchanged from ``reverse``): read-only. A session never modifies
the trace or the schema — every state it shows is *derived* from the immutable
record. Values are string reprs (the observable state), not live objects, so a
session cannot re-run the program — it replays what was recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from focustracer.core.loader import TraceLoader
from focustracer.core.reverse import Moment, Reconstructor, state_diff


def moment_to_dict(m: Moment) -> dict[str, Any]:
    """JSON-friendly view of a single moment (cursor position + state snapshot)."""
    return {
        "seq": m.seq,
        "event_id": m.event_id,
        "function": m.function,
        "file": m.file,
        "line": m.line,
        "source": m.source,
        "depth": m.depth,
        "state": {k: {"value": v[0], "type": v[1]} for k, v in m.state.items()},
    }


@dataclass
class DefSite:
    """The statement that last gave ``name`` its value at/before the cursor."""

    name: str
    moment: Moment
    old_value: Optional[str]
    new_value: Optional[str]


class ReplaySession:
    """A movable cursor over the reconstructed execution timeline.

    The timeline is the flat, execution-ordered list of line-level moments, each
    carrying the full observable state of its frame at that point. The cursor is
    an index into that list; ``step_forward`` / ``step_back`` move it, the
    ``jump_*`` helpers seek to a named point, and ``current`` / ``state`` read it.
    """

    def __init__(self, moments: list[Moment], recon: Optional[Reconstructor] = None):
        if not moments:
            raise ValueError(
                "trace has no line-level variable data — record with --detail normal or detailed"
            )
        self.moments = moments
        self._recon = recon
        self.cursor = 0

    # -- construction ------------------------------------------------------

    @classmethod
    def from_trace(cls, xml_path: str) -> "ReplaySession":
        doc = TraceLoader().load(xml_path)
        recon = Reconstructor(doc)
        return cls(recon.moments, recon)

    # -- cursor state ------------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.moments)

    @property
    def current(self) -> Moment:
        return self.moments[self.cursor]

    @property
    def can_forward(self) -> bool:
        return self.cursor < self.total - 1

    @property
    def can_back(self) -> bool:
        return self.cursor > 0

    def state(self) -> dict[str, tuple[str, str]]:
        """The observable variable state at the cursor: name -> (value, type)."""
        return self.current.state

    # -- navigation --------------------------------------------------------

    def _clamp(self, seq: int) -> int:
        return max(0, min(self.total - 1, seq))

    def step_forward(self, n: int = 1) -> Moment:
        self.cursor = self._clamp(self.cursor + max(1, n))
        return self.current

    def step_back(self, n: int = 1) -> Moment:
        self.cursor = self._clamp(self.cursor - max(1, n))
        return self.current

    def jump_to_seq(self, seq: int) -> Moment:
        self.cursor = self._clamp(seq)
        return self.current

    def jump_to_event(self, event_id: int) -> Moment:
        for m in self.moments:
            if m.event_id == event_id:
                self.cursor = m.seq
                return m
        raise ValueError(f"no line event with id {event_id}")

    def jump_to_line(self, line: int, function: Optional[str] = None) -> Moment:
        match: Optional[Moment] = None
        for m in self.moments:
            if m.line != line:
                continue
            if function and m.function != function:
                continue
            match = m  # last occurrence, mirrors reverse.moment_at_line
        if match is None:
            raise ValueError(
                f"no executed line {line}" + (f" in {function}" if function else "")
            )
        self.cursor = match.seq
        return match

    def jump_to_exception(self) -> Moment:
        m = self._recon.exception_moment() if self._recon else None
        if m is None:
            raise ValueError("no exception found in trace")
        self.cursor = m.seq
        return m

    # -- debugger stepping (frame-depth aware) -----------------------------
    # These mirror a standard debugger's Step Into / Over / Out, computed over
    # the recorded timeline using each moment's call-stack ``depth``.

    def _seek(self, forward: bool, pred) -> int:
        rng = range(self.cursor + 1, self.total) if forward else range(self.cursor - 1, -1, -1)
        for i in rng:
            if pred(self.moments[i]):
                return i
        return self.cursor  # no match ⇒ stay put

    def step_into(self, back: bool = False) -> Moment:
        """One executed line in either direction — enters any called function."""
        return self.step_back(1) if back else self.step_forward(1)

    def step_over(self, back: bool = False) -> Moment:
        """Next line in the current frame (or its caller), skipping called frames."""
        d = self.current.depth
        self.cursor = self._seek(forward=not back, pred=lambda m: m.depth <= d)
        return self.current

    def step_out(self, back: bool = False) -> Moment:
        """Advance until execution leaves the current frame, landing in its caller."""
        d = self.current.depth
        self.cursor = self._seek(forward=not back, pred=lambda m: m.depth < d)
        return self.current

    def step(self, action: str = "into", back: bool = False) -> Moment:
        """Dispatch a debugger step by name: 'into' | 'over' | 'out'."""
        fn = {"into": self.step_into, "over": self.step_over, "out": self.step_out}.get(
            action, self.step_into
        )
        return fn(back=back)

    # -- def-use -----------------------------------------------------------

    def def_of(self, name: str) -> Optional[DefSite]:
        """Where ``name`` last got its current value, at or before the cursor.

        Walks backward through the same frame looking for the moment at which
        ``name`` was added or changed — the assignment that produced the value
        visible at the cursor. Returns ``None`` if the variable is not defined
        at the cursor or its origin predates the recorded frame.
        """
        cur = self.current
        if name not in cur.state:
            return None
        frame_moments = [m for m in self.moments[: self.cursor + 1] if m.frame_id == cur.frame_id]
        prev: Optional[Moment] = None
        last_site: Optional[DefSite] = None
        for m in frame_moments:
            if prev is None:
                if name in m.state:
                    last_site = DefSite(name, m, None, m.state[name][0])
            else:
                for n, old_v, new_v in state_diff(prev, m):
                    if n == name:
                        last_site = DefSite(name, m, old_v, new_v)
                        break
            prev = m
        return last_site

    # -- serialisation -----------------------------------------------------

    def to_dict(self, window: int = 3) -> dict[str, Any]:
        """Cursor view for a UI: position, current snapshot, and neighbours.

        ``window`` line-events on each side are included as lightweight markers
        (no full state) so a caller can render a scrubber / timeline.
        """
        lo = max(0, self.cursor - window)
        hi = min(self.total, self.cursor + window + 1)
        timeline = []
        for m in self.moments[lo:hi]:
            entry = {
                "seq": m.seq,
                "event_id": m.event_id,
                "function": m.function,
                "line": m.line,
                "source": m.source,
                "is_cursor": m.seq == self.cursor,
            }
            if m.seq > lo:
                prev = self.moments[m.seq - 1]
                if prev.frame_id == m.frame_id:
                    # Forward-direction change: earlier value -> later value.
                    entry["change"] = [
                        {"name": n, "from": ev, "to": lv}
                        for n, ev, lv in state_diff(prev, m)
                    ]
            timeline.append(entry)
        return {
            "cursor": self.cursor,
            "total": self.total,
            "can_forward": self.can_forward,
            "can_back": self.can_back,
            "current": moment_to_dict(self.current),
            "timeline": timeline,
        }
