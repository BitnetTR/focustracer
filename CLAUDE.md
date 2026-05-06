# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

FocusTracer is an LLM-guided dynamic slicing and XML trace pipeline for Python debugging. It captures execution traces at runtime (zero source-code modification) and uses LLMs (Ollama or OpenCode) to intelligently suggest which functions to instrument.

## Commands

### Setup
```bash
pip install -e .
```

### Running the CLI
```bash
focustracer check-agent                          # verify LLM connectivity
focustracer suggest-targets <script.py> --hint "describe the bug"
focustracer run <script.py> --target mymodule.myfunction
focustracer run <script.py> --targets-file targets.json
focustracer gui                                  # launch web UI on port 8765
```

### Tests
```bash
# Run all unit tests
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_hook_basic.py

# Run integration/dev tests
python -m pytest tests/dev_test/

# Run with verbose output
python -m pytest tests/ -v
```

### Docker
```bash
docker build -t focustracer .
docker run -p 8765:8765 focustracer
```

### Frontend (GUI)
```bash
cd src/focustracer/gui/frontend
npm install
npm run build   # outputs to dist/
npm run dev     # dev server
```

## Architecture

### Core Tracing Engine (`src/focustracer/core/`)

- **`recorder.py` — `TraceRecorder`**: Main recording engine. Captures function calls, arguments, variable deltas, and loop iterations. Produces XML/JSON/JSONL output. Uses thread-local state for thread safety. `detail_level` controls verbosity (`minimal`, `normal`, `detailed`). Loop compaction reduces output for repeated iterations.

- **`patcher.py` — `DynamicPatcher`**: Runtime monkey-patching. Wraps target functions to activate `TraceRecorder` only during their execution — recording is scope-gated, not global. Zero overhead outside target scope.

- **`targeting.py` — `TargetManifest`**: Represents the set of trace targets (functions, files, lines, threads). Supports union merging: manual targets + AI-suggested targets are deduplicated and merged. Serialized as `.targets.json`.

- **`schema.py`**: XML schema builders for v1, v2, and v2.1 output formats.

### AI Agent Layer (`src/focustracer/agent/`)

- **`base.py` — `BaseAIAgent`**: Abstract interface. Subclass to add new LLM providers.
- **`ollama_client.py`**: Wraps local Ollama HTTP API. Default model: `qwen2.5:3b` at `http://localhost:11434`.
- **`opencode_client.py`**: Wraps the OpenCode CLI binary.

Both agents implement: target suggestion from code inventory, code analysis, and health checking.

### CLI (`src/focustracer/cli.py`)

Entry point with five commands: `check-agent`, `suggest-targets`, `run`, `gui`, `install`. The `suggest-targets` command builds a code inventory from the target script, sends it to the LLM with the user hint, and returns a `TargetManifest`. The `run` command merges manual `--target` flags with any `--targets-file` before patching.

### Web GUI (`src/focustracer/gui/`)

FastAPI backend + React/Vite frontend. Jobs are queued in-memory; real-time log streaming uses SSE. Settings persisted to `~/.focustracer/settings.json`. Frontend is pre-built to `dist/` and served as static files.

### Validation (`src/focustracer/validate/`)

XSD schema validation against `schema/trace_schema_v2.1.xsd`. Skip with `--skip-validate`.

## Key Design Invariants

- **Recording is scope-gated**: `DynamicPatcher` wraps the target function; recording only activates when execution enters that function. Don't enable global tracing.
- **TargetManifest merging uses union semantics**: Functions, files, lines, and threads are deduplicated sets. Preserve this when modifying `targeting.py`.
- **XML output requires CDATA for special characters**: Variable values with HTML entities must be wrapped in CDATA. See `recorder.py`.
- **AI agent interface is intentionally thin**: Agents return raw `TargetManifest` JSON; parsing/merging is handled by `targeting.py`, not the agent layer.

## Output

Default output directory: `output/`. Each run writes:
- `<script>_trace.xml` — execution trace
- `<script>.targets.json` — the manifest used for that run
