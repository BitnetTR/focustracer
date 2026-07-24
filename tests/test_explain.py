"""Stage 4 — LLM root-cause explanation from a slice.

The deterministic context builder is fully tested here; the LLM call itself is
verified by wiring (the slice context reaches the model) with a fake agent, so
no Ollama/OpenCode server is required.
"""

from focustracer import TraceContext
from focustracer.core.loader import TraceLoader
from focustracer.core.slicer import ExecutionModel, SliceCriterion, compute_slice
from focustracer.core.explain import (
    EXPLAIN_SYSTEM_PROMPT,
    build_slice_context,
    explain_slice,
)


def exc_divide(a, b):
    return a / b


def exc_compute(values):
    total = 0
    for v in values:
        total += exc_divide(10, v)
    return total


def exc_worker():
    return exc_compute([1, 2, 0])


def _exception_slice(tmp_path):
    out = str(tmp_path / "t.xml")
    with TraceContext(
        output_file=out, output_format="xml", schema_version="2.3",
        detail_level="detailed",
        target_functions=["exc_divide", "exc_compute", "exc_worker"],
    ):
        try:
            exc_worker()
        except ZeroDivisionError:
            pass
    model = ExecutionModel(TraceLoader().load(out), include_control=True)
    result = compute_slice(model, SliceCriterion(line=0, kind="exception"))
    return model, result


def test_context_includes_exception_and_values(tmp_path):
    model, result = _exception_slice(tmp_path)
    context = build_slice_context(model, result)

    assert "ZeroDivisionError" in context
    assert "return a / b" in context
    assert "CRITERION" in context
    # runtime values are annotated — the failing read b=0 must be visible
    assert "b=0" in context.replace(" ", "")


def test_context_is_smaller_than_full_trace(tmp_path):
    model, result = _exception_slice(tmp_path)
    context = build_slice_context(model, result)
    full = (tmp_path / "t.xml").read_text(encoding="utf-8")
    # The whole point: the model sees a compact slice, not the raw trace.
    assert len(context) < len(full)


class _FakeAgent:
    """Records the prompt passed to analyze_trace; returns a canned answer."""

    def __init__(self):
        self.seen_context = None
        self.seen_error = "unset"

    def analyze_trace(self, slice_context, *, error_context=None):
        self.seen_context = slice_context
        self.seen_error = error_context
        return "ROOT CAUSE: division by zero."


def test_explain_slice_passes_context_to_agent(tmp_path):
    model, result = _exception_slice(tmp_path)
    agent = _FakeAgent()

    explanation, context = explain_slice(agent, model, result, error_context="hi")

    assert explanation.startswith("ROOT CAUSE")
    assert agent.seen_context == context
    assert "return a / b" in agent.seen_context
    assert agent.seen_error == "hi"


def test_ollama_client_builds_explanation_prompt(monkeypatch):
    """The repurposed analyze_trace wraps the slice context in the explain prompt."""
    from focustracer.agent.ollama_client import OllamaClient

    captured = {}

    def _fake_generate(prompt, **kw):
        captured["prompt"] = prompt
        return "explained"

    client = OllamaClient()
    monkeypatch.setattr(client, "generate", _fake_generate)

    out = client.analyze_trace("SLICE-CONTEXT-HERE", error_context="ctx")
    assert out == "explained"
    assert EXPLAIN_SYSTEM_PROMPT in captured["prompt"]
    assert "SLICE-CONTEXT-HERE" in captured["prompt"]
    assert "ctx" in captured["prompt"]
