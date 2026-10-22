# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

FocusTracer is an LLM-guided dynamic slicing and XML trace pipeline for Python debugging. It captures execution traces at runtime (zero source-code modification) and uses LLMs (Ollama or OpenCode) to intelligently suggest which functions to instrument. On top of the recorded trace it provides post-mortem debugging primitives: backward dynamic slicing, LLM root-cause explanation, reverse execution (state rewind), and interactive forward/backward replay.

In the AI4SWENG program, FocusTracer is the trace engine for **KIO2** ("Bug Locate & Fix: Reverse Execution & Dynamic Slicing"). Per the finalized D2.6 requirements, FocusTracer directly implements FR-KIO2-07 (trace recorder) and feeds FR-KIO2-02 (interactive forward/backward replay) and FR-KIO2-04 (post-mortem inspection). LLM-based *fix generation* is out of KIO2 scope (it belongs to KIO7); the `explain` command stays as a standalone convenience, and in the KIO2 integration the LLM step is a hand-off to KIO7.

## Commands

### Setup
```bash
pip install -e .
```

### Running the CLI
```bash
focustracer check-agent --agent ollama --model qwen2.5:3b   # verify LLM connectivity
focustracer install                                          # install/manage agents, pull Ollama models
focustracer suggest-targets --target-script <script.py> --hint "describe the bug"
focustracer run --target-script <script.py> --function myfunc --detail detailed --schema-version 2.3
focustracer run --target-script <script.py>                  # no --function ⇒ trace all functions
focustracer load <trace.xml>                                 # display a saved trace (post-mortem)
focustracer slice <trace.xml> --at-exception                 # backward dynamic slice (root-cause)
focustracer explain <trace.xml> --at-exception               # LLM root-cause from the slice
focustracer reverse <trace.xml> --at-exception --step-back 6 # reverse execution / state rewind
focustracer replay <trace.xml> --seq 0 --step 3 --window 2   # interactive forward/backward stepping
focustracer gui                                              # launch web UI
```

Post-mortem commands (`slice`, `explain`, `reverse`, `replay`) need a `detailed`,
schema ≥ 2.3 trace (the default for `run`). `slice`/`explain`/`reverse` accept a
criterion (`--at [FILE:]LINE[:VAR]`) or default to the recorded exception.

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

- **`schema.py`**: XML schema builders for v1, v2, v2.1, v2.2, and v2.3 output formats. v2.3 adds `reads` (use-set) capture required for dynamic slicing.

- **`slicer.py`**: Backward dynamic slicing over a saved trace — data + control dependencies from a criterion (a value or the crash). Needs a schema ≥ 2.3, `detailed` trace. Writes a `<slice>` element into `<trace>.sliced.xml`.

- **`explain.py`**: Builds a value-annotated slice context and drives LLM root-cause explanation. The model is given the *slice*, not the raw trace. Standalone convenience — in the KIO2 integration the LLM step hands off to KIO7.

- **`reverse.py` — `Reconstructor`**: Reverse execution / state rewind. Reconstructs per-frame observable state at each executed line from the trace's reversible deltas; `reverse_trace` returns state at a point plus N steps back. Read-only, no re-run.

- **`replay.py` — `ReplaySession`**: Interactive replay — a movable cursor over the reconstructed timeline (`step_forward`/`step_back`/`jump_to_*`/`state`/`def_of`/`to_dict`). Reuses `reverse.Reconstructor`. Read-only. Realises FR-KIO2-02 (forward/backward navigation with state inspection).

- **`align.py` — `TraceSet` / `AlignedPair`**: Trace alignment (Needleman-Wunsch over the executed
  `function:line` sequences). `align_traces`/`trace_distance` give the pairwise distance (0 for identical
  runs) and `Alignment.divergences()` collapses the gaps into readable regions. `AlignedPair` is a
  two-trace session: drive a cursor on A (`seek`/`step`) and read the aligned point, state and
  `state_delta()` in B. `TraceSet` holds N traces — distance matrix, medoid (reference run) and outlier.
  Realises FR-KIO2-03. Note: the distance measures *control flow*; runs that differ only in values have
  distance 0 and surface through `state_delta()`.

- **`loader.py` — `TraceLoader`/`TraceDocument`**: Parses a saved trace XML into an in-memory document consumed by slicer/reverse/replay.

### AI Agent Layer (`src/focustracer/agent/`)

- **`base.py` — `BaseAIAgent`**: Abstract interface. Subclass to add new LLM providers.
- **`ollama_client.py`**: Wraps local Ollama HTTP API. Default model: `qwen2.5:3b` at `http://localhost:11434`.
- **`opencode_client.py`**: Wraps the OpenCode CLI binary.

Both agents implement: target suggestion from code inventory, code analysis, and health checking.

### CLI (`src/focustracer/cli.py`)

Entry point with commands: `check-agent`, `install`, `suggest-targets`, `run`, `load`, `slice`, `explain`, `reverse`, `replay`, `gui`. The `suggest-targets` command builds a code inventory from the target script, sends it to the LLM with the user hint, and returns a `TargetManifest`. The `run` command merges manual `--function`/`--file`/`--line` targets (and `--auto-targets` AI suggestions) before patching. The post-mortem commands (`slice`, `explain`, `reverse`, `replay`) operate on a saved trace and never re-run the program.

### Web GUI (`src/focustracer/gui/`)

FastAPI backend + React/Vite frontend. Jobs are queued in-memory; real-time log streaming uses SSE. Settings persisted to `~/.focustracer/settings.json`. Frontend is pre-built to `dist/` and served as static files. The GUI has **parity with the CLI**: opening a trace under *Trace Logs* exposes **Slice / Reverse / Replay / Explain** tabs (endpoints `POST /api/trace/{slice,reverse,replay,explain}`; the replay endpoint is stateless — the client keeps `seq` and re-POSTs with `seq±1`). Settings › AI Agent has a **Models** section that lists and pulls Ollama models with live progress (`GET /api/ollama/models`, `POST /api/ollama/pull`).

### Validation (`src/focustracer/validate/`)

XSD schema validation against the trace's schema version (v1 … v2.3) in `schema/`. Slicing requires v2.3. Skip with `--skip-validate`.

## Key Design Invariants

- **Recording is scope-gated**: `DynamicPatcher` wraps the target function; recording only activates when execution enters that function. Don't enable global tracing.
- **TargetManifest merging uses union semantics**: Functions, files, lines, and threads are deduplicated sets. Preserve this when modifying `targeting.py`.
- **XML output requires CDATA for special characters**: Variable values with HTML entities must be wrapped in CDATA. See `recorder.py`.
- **AI agent interface is intentionally thin**: Agents return raw `TargetManifest` JSON; parsing/merging is handled by `targeting.py`, not the agent layer.

## Output

Default output directory: `output/`. Each run writes:
- `<script>_trace.xml` — execution trace
- `<script>.targets.json` — the manifest used for that run

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool` or `query_graph_tool` instead of Grep
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
