"""Backward dynamic slicing over a FocusTracer trace.

Given a saved trace (loaded via :class:`~focustracer.core.loader.TraceLoader`) and
a slice *criterion* — an execution point plus a variable — this computes the
**backward dynamic slice**: the set of executed statements that actually
influenced that value on this run (Korel & Laski 1988; Agrawal & Horgan 1990).

Method
------
1. Flatten the hierarchical trace into a linear *execution history* of steps,
   each tagged with the frame instance it ran in, the variables it **uses**
   (from the recorded ``<reads>`` set) and the variables it **defines** (from an
   ``ast`` parse of the line — Store-context names + augmented-assignment
   targets). Loop headers are synthesised (they are ``<loop>`` attributes, not
   line events) as a def of the loop target and a use of the iterable.
2. Forward pass — resolve each use to its **reaching definition** (the most
   recent prior def of that name in the same frame), giving data-dependency
   edges. Parameters with no in-frame def link to the call site (interprocedural,
   over-approximated: all call-site reads are pulled in). Control-dependency
   edges link each step to its nearest enclosing ``if``/``for``/``while`` header
   (structural, from the source AST).
3. Backward reachability from the criterion over those edges = the slice.

Defs come from the AST, never from ``<delta>``, so the one-event offset in
FocusTracer's delta attribution (settrace fires before a line runs) does not
affect slicing.
"""

from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from focustracer.core.loader import TraceDocument, TraceLoader


# ---------------------------------------------------------------------------
# Per-line def/use extraction
# ---------------------------------------------------------------------------


def parse_line_def_use(source_line: str) -> tuple[list[str], list[str]]:
    """Return ``(uses, defs)`` variable names for a single source line.

    ``uses`` = Name/Load + augmented-assignment targets (read before write).
    ``defs`` = Name/Store + augmented-assignment targets. Control-flow headers
    (``if``/``for``/``while`` — no standalone body) get a ``pass`` appended so
    they still parse. Best-effort: unparseable lines yield empty sets.
    """
    candidates = [source_line]
    if source_line.strip().endswith(":"):
        candidates.append(source_line + " pass")

    tree: Optional[ast.AST] = None
    for candidate in candidates:
        try:
            tree = ast.parse(candidate, mode="exec")
            break
        except SyntaxError:
            continue
    if tree is None:
        return [], []

    uses: list[str] = []
    defs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                _add(uses, node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                _add(defs, node.id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            _add(uses, node.target.id)  # x += ... reads x too
    return uses, defs


def _add(seq: list[str], name: str) -> None:
    if name not in seq:
        seq.append(name)


# ---------------------------------------------------------------------------
# Control-dependency map (source AST)
# ---------------------------------------------------------------------------


def build_control_map(source: str) -> dict[int, int]:
    """Map each statement line to its nearest enclosing predicate header line.

    Covers ``if``/``elif``/``else``/``for``/``while`` nesting (structural
    approximation of control dependence, exact for structured Python). Function
    bodies reset — a top-level statement in a function is not control-dependent
    on the ``def``.
    """
    mapping: dict[int, int] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return mapping

    def walk_body(stmts: Iterable[ast.stmt], header: Optional[int]) -> None:
        for stmt in stmts:
            if header is not None:
                mapping[stmt.lineno] = header
            if isinstance(stmt, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                walk_body(stmt.body, stmt.lineno)
                walk_body(stmt.orelse, stmt.lineno)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk_body(stmt.body, None)  # new scope, no inherited control
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                walk_body(stmt.body, header)
            elif isinstance(stmt, ast.Try):
                walk_body(stmt.body, header)
                for handler in stmt.handlers:
                    walk_body(handler.body, header)
                walk_body(stmt.orelse, header)
                walk_body(stmt.finalbody, header)

    walk_body(tree.body, None)
    return mapping


# ---------------------------------------------------------------------------
# Flattened execution model
# ---------------------------------------------------------------------------


@dataclass
class Step:
    seq: int
    frame_id: int
    line: int
    file: str
    function: str
    source: str
    uses: list[str]
    defs: list[str]
    kind: str  # "line" | "return" | "exception" | "loop_header"
    event_id: Optional[int] = None
    data_deps: set[int] = field(default_factory=set)
    control_dep: Optional[int] = None


@dataclass
class Frame:
    frame_id: int
    function: str
    file: str
    parent_frame_id: Optional[int]
    call_seq: Optional[int]  # seq of the call-site step in the parent frame
    params: list[str]
    return_seq: Optional[int] = None
    exception_seq: Optional[int] = None


class ExecutionModel:
    """Flattens a TraceDocument into steps + frames and computes dependencies."""

    def __init__(self, doc: TraceDocument, include_control: bool = True):
        self.steps: list[Step] = []
        self.frames: dict[int, Frame] = {}
        self._frame_counter = 0
        self.include_control = include_control
        self._control_maps: dict[str, dict[int, int]] = {}
        self._flatten(doc.nodes, frame_id=None)
        self._compute_dependencies()

    # -- flattening --------------------------------------------------------

    def _new_frame(
        self, function: str, file: str, parent: Optional[int], call_seq: Optional[int],
        params: list[str],
    ) -> int:
        fid = self._frame_counter
        self._frame_counter += 1
        self.frames[fid] = Frame(fid, function, file, parent, call_seq, params)
        return fid

    def _emit(self, **kw: Any) -> Step:
        step = Step(seq=len(self.steps), **kw)
        self.steps.append(step)
        return step

    def _last_seq_in_frame(self, frame_id: Optional[int]) -> Optional[int]:
        for step in reversed(self.steps):
            if step.frame_id == frame_id:
                return step.seq
        return None

    def _flatten(
        self, nodes: list[dict[str, Any]], frame_id: Optional[int],
        ctx_func: str = "", ctx_file: str = "",
    ) -> None:
        for node in nodes:
            ntype = node.get("type")
            if ntype == "thread":
                self._flatten(node.get("children", []), frame_id, ctx_func, ctx_file)
            elif ntype == "scope":
                call_seq = self._last_seq_in_frame(frame_id)
                params = list(node.get("arguments", {}).keys())
                func = node.get("function", "")
                file = node.get("file", "")
                fid = self._new_frame(func, file, frame_id, call_seq, params)
                self._flatten(node.get("children", []), fid, func, file)
                frame = self.frames[fid]
                if node.get("exception") is not None:
                    frame.exception_seq = self._last_seq_in_frame(fid)
                if node.get("return_value") is not None:
                    frame.return_seq = self._last_seq_in_frame(fid)
            elif ntype == "loop":
                self._flatten_loop(node, frame_id, ctx_func, ctx_file)
            elif ntype == "event":
                self._flatten_event(node["data"], frame_id, ctx_func, ctx_file)

    def _flatten_loop(
        self, node: dict[str, Any], frame_id: Optional[int], ctx_func: str, ctx_file: str
    ) -> None:
        header_uses, header_defs = parse_line_def_use(node.get("source", ""))
        for iteration in node.get("iteration_list", []):
            # One synthetic loop-header step per iteration: defines the loop
            # target, uses the iterable. Body events are control-dependent on it.
            self._emit(
                frame_id=frame_id if frame_id is not None else -1,
                line=node.get("line", 0), file=ctx_file, function=ctx_func,
                source=node.get("source", ""), uses=list(header_uses),
                defs=list(header_defs), kind="loop_header",
            )
            self._flatten(iteration.get("events", []), frame_id, ctx_func, ctx_file)

    def _flatten_event(
        self, data: dict[str, Any], frame_id: Optional[int], ctx_func: str, ctx_file: str
    ) -> None:
        etype = data.get("event_type", "")
        if etype not in ("line", "return", "exception"):
            return
        source = data.get("source", "")
        _uses, defs = parse_line_def_use(source)
        reads = data.get("reads") or {}
        uses = list(reads.keys()) if reads else _uses
        self._emit(
            frame_id=frame_id if frame_id is not None else -1,
            line=data.get("line", 0),
            file=data.get("file") or ctx_file,
            function=data.get("function") or ctx_func,
            source=source, uses=uses, defs=defs, kind=etype,
            event_id=data.get("id"),
        )

    # -- dependency edges --------------------------------------------------

    def _control_map_for(self, file: str) -> dict[int, int]:
        if file not in self._control_maps:
            src = ""
            try:
                src = Path(file).read_text(encoding="utf-8")
            except Exception:
                src = ""
            self._control_maps[file] = build_control_map(src) if src else {}
        return self._control_maps[file]

    def _compute_dependencies(self) -> None:
        last_def: dict[tuple[int, str], int] = {}
        last_line: dict[tuple[int, int], int] = {}  # (frame, line) -> seq

        for step in self.steps:
            # data dependencies: each use -> its reaching definition
            for name in step.uses:
                key = (step.frame_id, name)
                if key in last_def:
                    step.data_deps.add(last_def[key])
                else:
                    frame = self.frames.get(step.frame_id)
                    if frame and name in frame.params and frame.call_seq is not None:
                        step.data_deps.add(frame.call_seq)  # param <- call site
            # control dependency (structural)
            if self.include_control and step.file:
                header_line = self._control_map_for(step.file).get(step.line)
                if header_line is not None:
                    dep = last_line.get((step.frame_id, header_line))
                    if dep is not None and dep != step.seq:
                        step.control_dep = dep
            # a body step is control-dependent on its enclosing loop header too
            # (loop headers carry no file, matched structurally above when the
            # predicate is an if/while; the loop case is handled via def of the
            # loop variable, which already ties the body in through data deps).

            # register defs / line occurrence AFTER resolving uses
            for name in step.defs:
                last_def[(step.frame_id, name)] = step.seq
            last_line[(step.frame_id, step.line)] = step.seq

        # return-value linking: a call site depends on the callee's return
        for frame in self.frames.values():
            if frame.call_seq is None:
                continue
            target = frame.return_seq if frame.return_seq is not None else frame.exception_seq
            if target is not None:
                self.steps[frame.call_seq].data_deps.add(target)


# ---------------------------------------------------------------------------
# Slice computation
# ---------------------------------------------------------------------------


@dataclass
class SliceCriterion:
    line: int
    var: Optional[str] = None
    file: Optional[str] = None
    kind: str = "explicit"  # "explicit" | "exception"


@dataclass
class SliceResult:
    criterion_label: str
    criterion_seq: Optional[int]
    include_control: bool
    seqs: list[int]  # sliced step seqs, execution order
    dependency: dict[int, str]  # seq -> criterion|data|control


def _frame_depth(model: ExecutionModel, fid: int) -> int:
    depth = 0
    cur = model.frames[fid].parent_frame_id
    while cur is not None:
        depth += 1
        cur = model.frames[cur].parent_frame_id
    return depth


def _find_exception_criterion(model: ExecutionModel) -> Optional[Step]:
    """Innermost exception origin: the failing line in the deepest frame.

    Exceptions are recorded as a scope-level ``<exception>`` (captured during
    flattening as ``frame.exception_seq``), or occasionally as an explicit
    exception event step.
    """
    best_frame: Optional[Frame] = None
    best_depth = -1
    for fid, frame in model.frames.items():
        if frame.exception_seq is None:
            continue
        depth = _frame_depth(model, fid)
        if depth >= best_depth:
            best_depth = depth
            best_frame = frame

    if best_frame is not None and best_frame.exception_seq is not None:
        # The failing line = last executed line in the raising frame.
        for step in reversed(model.steps):
            if step.frame_id == best_frame.frame_id and step.kind == "line":
                return step
        return model.steps[best_frame.exception_seq]

    # Fallback: an explicit exception event step, deepest first.
    best_step: Optional[Step] = None
    best_depth = -1
    for step in model.steps:
        if step.kind == "exception":
            d = _frame_depth(model, step.frame_id) if step.frame_id in model.frames else 0
            if d >= best_depth:
                best_depth = d
                best_step = step
    return best_step


def compute_slice(model: ExecutionModel, criterion: SliceCriterion) -> SliceResult:
    """Backward reachability from the criterion over data + control edges."""
    if criterion.kind == "exception":
        start = _find_exception_criterion(model)
        if start is None:
            raise ValueError("no exception found in trace")
        label = f"exception@{Path(start.file).name}:{start.line}"
        seeds = set(start.uses)
    else:
        start = _find_explicit_criterion(model, criterion)
        if start is None:
            raise ValueError(
                f"no executed step matches criterion line {criterion.line}"
            )
        label = f"{Path(start.file).name}:{start.line}"
        if criterion.var:
            label += f":{criterion.var}"
        seeds = {criterion.var} if criterion.var else set(start.uses)

    dependency: dict[int, str] = {start.seq: "criterion"}
    in_slice: set[int] = {start.seq}

    # Worklist over steps; each carries the set of live variable names still to
    # explain within that step's frame. We push the criterion's seed uses onto
    # the reaching definitions of the start step.
    worklist: list[int] = []

    def pull(seq: int, dep_kind: str) -> None:
        if seq not in in_slice:
            in_slice.add(seq)
            dependency[seq] = dep_kind
            worklist.append(seq)
        elif dependency.get(seq) == "control" and dep_kind == "data":
            dependency[seq] = "data"  # data is the stronger label

    # Seed: definitions reaching the criterion's seed variables, resolved as of
    # the start step, plus the start's own edges.
    _seed_reaching(model, start, seeds, pull)
    worklist.append(start.seq)

    while worklist:
        seq = worklist.pop()
        step = model.steps[seq]
        for dep in step.data_deps:
            pull(dep, "data")
        if step.control_dep is not None:
            pull(step.control_dep, "control")

    seqs = sorted(in_slice)
    return SliceResult(label, start.seq, model.include_control, seqs, dependency)


def _seed_reaching(model: ExecutionModel, start: Step, seeds: set[str], pull) -> None:
    """Pull the reaching definition of each seed var as of the start step."""
    last_def: dict[tuple[int, str], int] = {}
    for step in model.steps:
        if step.seq >= start.seq:
            break
        for name in step.defs:
            last_def[(step.frame_id, name)] = step.seq
    for name in seeds:
        key = (start.frame_id, name)
        if key in last_def:
            pull(last_def[key], "data")
        else:
            frame = model.frames.get(start.frame_id)
            if frame and name in frame.params and frame.call_seq is not None:
                pull(frame.call_seq, "data")


def _find_explicit_criterion(
    model: ExecutionModel, criterion: SliceCriterion
) -> Optional[Step]:
    match: Optional[Step] = None
    for step in model.steps:
        if step.kind == "loop_header":
            continue
        if step.line != criterion.line:
            continue
        if criterion.file and Path(step.file).name != Path(criterion.file).name:
            continue
        if criterion.var and (
            criterion.var not in step.defs and criterion.var not in step.uses
        ):
            continue
        match = step  # keep the last occurrence
    return match


# ---------------------------------------------------------------------------
# XML emission
# ---------------------------------------------------------------------------


def slice_result_to_dicts(model: ExecutionModel, result: SliceResult) -> list[dict[str, Any]]:
    """Sliced steps as ordered plain dicts (for XML/JSON/display)."""
    out: list[dict[str, Any]] = []
    for seq in result.seqs:
        step = model.steps[seq]
        out.append(
            {
                "line": step.line,
                "event_id": step.event_id,
                "function": step.function,
                "file": step.file,
                "source": step.source,
                "dependency": result.dependency.get(seq, "data"),
            }
        )
    return out


def build_slice_element(model: ExecutionModel, result: SliceResult) -> ET.Element:
    """Build the ``<slice>`` element (v2.3 SliceType)."""
    slice_elem = ET.Element("slice")
    slice_elem.set("criterion", result.criterion_label)
    if result.criterion_seq is not None:
        ev = model.steps[result.criterion_seq].event_id
        if ev is not None:
            slice_elem.set("criterion_event", str(ev))
    slice_elem.set("include_control", "true" if result.include_control else "false")
    for d in slice_result_to_dicts(model, result):
        node = ET.SubElement(slice_elem, "node")
        node.set("line", str(d["line"]))
        if d["event_id"] is not None:
            node.set("event_id", str(d["event_id"]))
        if d["function"]:
            node.set("function", d["function"])
        node.set("dependency", d["dependency"])
        if d["source"]:
            node.set("source", d["source"])
    return slice_elem


def annotate_trace_with_slice(
    xml_path: str,
    model: ExecutionModel,
    result: SliceResult,
    output_path: Optional[str] = None,
) -> str:
    """Embed a ``<slice>`` element into a copy of the trace XML.

    Non-destructive by default: writes ``<stem>.sliced.xml`` next to the input
    unless ``output_path`` is given. Any pre-existing ``<slice>`` is replaced.
    Returns the written path.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for existing in root.findall("slice"):
        root.remove(existing)
    root.append(build_slice_element(model, result))  # after metadata, events

    if output_path is None:
        p = Path(xml_path)
        output_path = str(p.with_name(p.stem + ".sliced" + p.suffix))
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path


def slice_trace(
    xml_path: str,
    *,
    at_exception: bool = False,
    at: Optional[str] = None,
    include_control: bool = True,
) -> tuple[ExecutionModel, SliceResult]:
    """Load a trace and compute a slice from an ``--at-exception`` or
    ``--at file:line:var`` specification."""
    doc = TraceLoader().load(xml_path)
    model = ExecutionModel(doc, include_control=include_control)
    if at_exception:
        criterion = SliceCriterion(line=0, kind="exception")
    elif at:
        criterion = _parse_at_spec(at)
    else:
        raise ValueError("provide at_exception=True or at='file:line:var'")
    result = compute_slice(model, criterion)
    return model, result


def _parse_at_spec(spec: str) -> SliceCriterion:
    """Parse ``file.py:line:var`` / ``line:var`` / ``line``."""
    parts = spec.split(":")
    if len(parts) >= 3:
        return SliceCriterion(line=int(parts[-2]), var=parts[-1], file=":".join(parts[:-2]))
    if len(parts) == 2:
        # Could be "line:var" or "file:line". Prefer line:var if first is int.
        if parts[0].isdigit():
            return SliceCriterion(line=int(parts[0]), var=parts[1])
        return SliceCriterion(line=int(parts[1]), file=parts[0])
    return SliceCriterion(line=int(parts[0]))
