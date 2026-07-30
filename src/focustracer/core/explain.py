"""LLM root-cause explanation from a backward dynamic slice.

Stage 4 of the KIO2 pipeline. Instead of dumping a whole trace at the model
(imprecise and token-heavy), we hand it the *slice* — the minimal chain of
statements that produced the value or exception — annotated with the actual
runtime values each statement read. That is a compact, high-signal prompt.

``build_slice_context`` is deterministic (fully testable without an LLM);
``explain_slice`` calls the agent.
"""

from __future__ import annotations

from typing import Optional

from focustracer.core.slicer import ExecutionModel, SliceResult


EXPLAIN_SYSTEM_PROMPT = (
    "You are a debugging assistant. You are given a BACKWARD DYNAMIC SLICE: the "
    "minimal set of executed statements that produced a specific value or "
    "exception on one real run, in execution order, annotated with the actual "
    "runtime values each statement read. Lines marked CRITERION are the target; "
    "[control] marks a control-dependency (a branch/loop that caused execution).\n\n"
    "Using ONLY the slice below, answer concisely:\n"
    "1. ROOT CAUSE: one sentence naming the specific statement and value at fault.\n"
    "2. WHY: the causal chain in plain language, following the runtime values.\n"
    "3. FIX: a concrete, minimal code change.\n"
    "Do not speculate beyond the slice."
)


def build_slice_context(model: ExecutionModel, result: SliceResult) -> str:
    """Render the slice (with runtime values) as a compact LLM prompt context.

    Deterministic — no LLM involved.
    """
    lines: list[str] = [f"Slice criterion: {result.criterion_label}"]

    crit = (
        model.steps[result.criterion_seq]
        if result.criterion_seq is not None
        else None
    )
    if crit is not None:
        frame = model.frames.get(crit.frame_id)
        if frame and frame.exception_info:
            exc = frame.exception_info
            lines.append(
                f"Exception: {exc.get('type', '')}: {exc.get('value', '')}".rstrip(": ")
            )

    lines.append("")
    lines.append(
        "Backward dynamic slice (execution order) — statements that produced "
        "this value, with the runtime values each one read:"
    )
    for seq in result.seqs:
        step = model.steps[seq]
        dep = result.dependency.get(seq, "data")
        vals = ", ".join(f"{k}={v}" for k, v in step.values.items())
        val_str = f"   [{vals}]" if vals else ""
        tag = {"criterion": "  <-- CRITERION", "control": "  [control]"}.get(dep, "")
        fn = step.function or "?"
        lines.append(f"  L{step.line} {fn}: {step.source}{val_str}{tag}")
    return "\n".join(lines)


def explain_slice(
    agent,
    model: ExecutionModel,
    result: SliceResult,
    *,
    error_context: Optional[str] = None,
) -> tuple[str, str]:
    """Build the slice context and ask the agent to explain it.

    Returns ``(explanation, context)`` — the context is returned too so callers
    can show or persist exactly what the model saw.
    """
    context = build_slice_context(model, result)
    explanation = agent.analyze_trace(context, error_context=error_context)
    return explanation, context
