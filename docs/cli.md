# CLI Reference

All commands are available as `focustracer <command>` or `python -m focustracer <command>`.

| Group | Commands |
|---|---|
| Setup | [`install`](#install), [`check-agent`](#check-agent), [`gui`](#gui) |
| Capture | [`suggest-targets`](#suggest-targets), [`run`](#run) |
| Analysis (offline, on a saved trace) | [`load`](#load), [`slice`](#slice), [`reverse`](#reverse), [`replay`](#replay), [`align`](#align) |
| Analysis (needs an LLM) | [`explain`](#explain) |

The examples use the sample script shipped in the repository: `tests/fixtures/cli_sample_app.py`.

---

## Common options

### Agent options

Used by `check-agent`, `suggest-targets`, `run` and `explain`.

| Option | Default | Description |
|---|---|---|
| `--agent` | `ollama` | LLM backend: `ollama` or `opencode` |
| `--model` | `qwen2.5:3b` | Model name |
| `--ollama-url` | `http://localhost:11434` | Ollama base URL |
| `--opencode-cmd` | `opencode` | OpenCode CLI executable |

### Target filters

Used by `suggest-targets` and `run`. Every flag can be repeated; manual and AI targets are merged (union).

| Option | Format | Description |
|---|---|---|
| `--function` | `worker` or `module.Class.method` | Function whose call activates tracing |
| `--file` | relative or absolute path | Only record events from this file inside activated scopes |
| `--line` | `path/to/file.py:42` | Only record this line inside activated scopes |
| `--thread-name` | `CLI-Worker` | Only record events from this thread inside activated scopes |

Activation is function based: `--file`, `--line` and `--thread-name` only *filter* inside a scope
that a function target has activated. With `run`, if no function target is given (and no
`--auto-targets`), every function defined in the target script is traced.

### Trace options

Used by `run` and by `suggest-targets --execute`.

| Option | Default | Description |
|---|---|---|
| `--schema-version` | `2.3` | Schema version written into the trace |
| `--detail` | `detailed` | `minimal`, `normal` or `detailed`. `slice` / `explain` need `detailed` |
| `--max-depth` | `100` | Maximum call depth recorded |
| `--max-iterations` | – | Max iterations written per compacted loop |
| `--skip-validate` | off | Skip post-run XML validation |

---

## Setup commands

### `install`

Shows the status of the AI backends and guides their installation.

```bash
python -m focustracer install --status          # status snapshot and exit
python -m focustracer install --agent ollama    # Ollama installer flow (incl. model pull)
python -m focustracer install --agent opencode
```

Options: `--agent {ollama,opencode}`, `--model`, `--status`, `--ollama-url`, `--opencode-cmd`.

### `check-agent`

Checks that the backend is reachable and the model is available. Prints a JSON health object
(`ok`, `model_available`, `available_models`, `error`, …).

```bash
python -m focustracer check-agent --agent ollama --model qwen2.5:3b --ollama-url http://localhost:11434
python -m focustracer check-agent --agent opencode --model opencode/minimax-m2.5-free --opencode-cmd opencode
```

Options: [agent options](#agent-options).

### `gui`

Starts the web UI. Every analysis command (`slice`, `reverse`, `replay`, `explain`) is available
from **Trace Logs** → open a trace → **Slice / Reverse / Replay / Explain** tabs. Ollama models can be
pulled from **Settings › AI Agent › Models**.

```bash
python -m focustracer gui
python -m focustracer gui --host 0.0.0.0 --port 9000 --no-browser
```

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8765` | Port |
| `--no-browser` | off | Do not open the browser automatically |

---

## Capture commands

### `suggest-targets`

Builds a lightweight code inventory and asks the LLM which targets to trace.
By default it **only prints the suggested manifest (JSON)** — it does not run the script or write a trace.

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Trace the worker path and multiplication logic"
```

Save the manifest:

```bash
# timestamped file under --output-dir
python -m focustracer suggest-targets --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py --save-manifest

# explicit path
python -m focustracer suggest-targets --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --manifest-output output/cli_sample_app.targets.json
```

Suggest and trace in one command:

```bash
python -m focustracer suggest-targets \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Trace the worker path and multiplication logic" \
  --execute \
  --trace-output output/auto_from_suggest.xml
```

| Option | Default | Description |
|---|---|---|
| `--project-root` | **required** | Root directory for the code inventory |
| `--target-script` | **required** | Script to (eventually) run |
| `--hint` | – | Extra hint for the LLM |
| `--error-context` | – | Error / traceback / log text for the LLM |
| `--execute` | off | Run tracing immediately with the merged manifest |
| `--save-manifest` | off | Write the manifest to `--output-dir` with a timestamped name |
| `--manifest-output` | – | Write the manifest to this path |
| `--output-dir` | `output` | Directory for `--save-manifest` |
| `--trace-output` | auto | Trace XML path when `--execute` is used |
| `--trace-output-dir` | `output` | Directory for the auto-named trace when `--execute` is used |

Plus [agent options](#agent-options), [target filters](#target-filters) and
[trace options](#trace-options) (the latter only apply with `--execute`).

### `run`

Runs the target script, writes the XML trace and the merged target manifest next to it, and validates the XML.

```bash
# trace every function in the script
python -m focustracer run --target-script app.py

# focus on specific functions / threads
python -m focustracer run \
  --target-script tests/fixtures/cli_sample_app.py \
  --function worker \
  --thread-name CLI-Worker \
  --output output/sample_trace.xml

# let the LLM choose the targets
python -m focustracer run \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --auto-targets \
  --hint "Trace the worker path and multiplication logic"
```

| Option | Default | Description |
|---|---|---|
| `--target-script` | **required** | Script to run |
| `--project-root` | script directory | Root directory for the code inventory (used with `--auto-targets`) |
| `--auto-targets` | off | Ask the LLM for targets |
| `--hint` | – | Extra hint for the LLM |
| `--error-context` | – | Error / traceback / log text for the LLM |
| `--output` | auto | Trace XML path |
| `--output-dir` | `output` | Directory for the auto-named trace (`YYYYmmdd_HHMMSS_<script>.xml`) |

Plus [agent options](#agent-options), [target filters](#target-filters) and [trace options](#trace-options).

---

## Analysis commands

All analysis commands read a saved trace and never re-run the program.

### `load`

Displays a saved trace (post-mortem view): execution tree and statistics.

```bash
python -m focustracer load output/sample_trace.xml
python -m focustracer load output/sample_trace.xml --summary
python -m focustracer load output/sample_trace.xml --filter-function worker --filter-thread CLI-Worker
```

| Option | Description |
|---|---|
| `--summary` | Statistics table only, no execution tree |
| `--filter-function NAME` | Only scopes of this function |
| `--filter-thread ID_OR_NAME` | Only events of this thread |
| `--no-validate` | Skip XSD validation before display |

### `slice`

Computes a **backward dynamic slice**: the statements that actually influenced a value in this run
(data + control dependencies). Requires a `detailed` trace with schema ≥ 2.3 (the `run` default).
Writes a `<slice>` element into `<trace>.sliced.xml` and validates it against the v2.3 XSD.

```bash
python -m focustracer slice output/sample_trace.xml --at-exception          # root cause of the crash
python -m focustracer slice output/sample_trace.xml --at app.py:42:total    # what produced `total` at line 42
python -m focustracer slice output/sample_trace.xml --at-exception --no-control
```

| Option | Description |
|---|---|
| `--at-exception` | Slice from the innermost exception's failing line (default when `--at` is not given) |
| `--at [FILE:]LINE[:VAR]` | Slice criterion, e.g. `app.py:42:total` or `42:total` |
| `--no-control` | Data dependencies only |
| `--output` | Output path (default `<trace>.sliced.xml`) |
| `--no-validate` | Skip XSD validation of the output |

Output markers: `◆` criterion, `▸` control dependency, `·` data dependency.

### `explain`

Computes a slice and asks the LLM for a **root-cause explanation**. The model receives the slice
annotated with runtime values — not the raw trace — so small local models such as `qwen2.5:3b` work well.
The answer contains (1) the root cause, (2) the causal chain, (3) a concrete fix.

```bash
python -m focustracer explain output/sample_trace.xml --at-exception --model qwen2.5:3b
python -m focustracer explain output/sample_trace.xml --at-exception --show-context      # offline: show what the model gets
python -m focustracer explain output/sample_trace.xml --at app.py:42:total --output rootcause.md
```

| Option | Description |
|---|---|
| `--at-exception` / `--at` / `--no-control` | Same as `slice` |
| `--error-context` | Extra context passed to the model |
| `--show-context` | Print the slice context only; no LLM needed |
| `--output` | Write the explanation to a file |

Plus [agent options](#agent-options).

### `reverse`

**Reverse execution.** Reconstructs the observable program state at a point (the crash by default)
and steps backward, showing what each variable un-does (`undo total: 12 → 6`), across call boundaries.
Values are the recorded (string) state, not live objects.

```bash
python -m focustracer reverse output/sample_trace.xml --at-exception --step-back 6
python -m focustracer reverse output/sample_trace.xml --at-event 18
python -m focustracer reverse output/sample_trace.xml --at-line 42 --function compute
python -m focustracer reverse output/sample_trace.xml --at-exception --json rewind.json
```

| Option | Default | Description |
|---|---|---|
| `--at-exception` | default | Start at the crash |
| `--at-event ID` | – | Start at a line event ID |
| `--at-line LINE` | – | Start at a source line |
| `--function` | – | Disambiguate `--at-line` |
| `--step-back K` | `5` | Number of line events to rewind |
| `--json PATH` | – | Write the reconstructed state(s) to JSON |

### `replay`

**Interactive replay** — a movable cursor over the whole timeline. Seek, step forward or backward,
inspect the state at the cursor, and find which statement last defined a variable (def-use).

```bash
python -m focustracer replay output/sample_trace.xml --list                         # whole timeline
python -m focustracer replay output/sample_trace.xml --at-exception                 # state at the crash
python -m focustracer replay output/sample_trace.xml --seq 0 --step 3 --window 2    # 3 forward from index 0
python -m focustracer replay output/sample_trace.xml --at-line 42 --step -2 --def total

# debugger-style stepping (call-depth aware)
python -m focustracer replay output/sample_trace.xml --seq 1 --into
python -m focustracer replay output/sample_trace.xml --seq 1 --over
python -m focustracer replay output/sample_trace.xml --at-exception --out --back
```

| Option | Default | Description |
|---|---|---|
| `--at-exception` / `--at-event ID` / `--at-line LINE` / `--seq N` | index 0 | Start point |
| `--function` | – | Disambiguate `--at-line` |
| `--step N` | `0` | `+N` forward, `-N` backward from the start point |
| `--into` / `--over` / `--out` | – | Debugger step into / over / out (mutually exclusive) |
| `--back` | off | Apply `--into/--over/--out` backward |
| `--window K` | `3` | Neighbour events shown around the cursor |
| `--def VAR` | – | Show the statement that last defined `VAR` |
| `--list` | off | Print the whole timeline |
| `--json PATH` | – | Write the cursor view to JSON |

### `align`

Aligns two traces of the same program (e.g. a passing and a failing run) with global sequence
alignment and reports their distance. Identical traces have distance `0`.

```bash
python -m focustracer align output/pass.xml output/fail.xml
python -m focustracer align output/pass.xml output/fail.xml --show-alignment --json align.json
```

| Option | Description |
|---|---|
| `--show-alignment` | Print aligned statement pairs (matches and gaps) |
| `--json PATH` | Write distance and pairs to JSON |
