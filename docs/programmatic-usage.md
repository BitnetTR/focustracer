# Programmatic Usage

Public API (`from focustracer import ...`): `TraceContext`, `TraceRecorder`, `trace_function`,
`TargetManifest`, `DynamicPatcher`, `build_code_inventory`.

## `TraceContext` — context manager

Starts recording on enter; on exit it stops, saves the trace and prints a summary.

```python
from focustracer import TraceContext


def process(data):
    total = 0
    for item in data:
        total += item
    return total


with TraceContext(
    output_file="output/programmatic.xml",
    target_functions=["process"],
    detail_level="detailed",
    enable_threading=True,
):
    process([1, 2, 3])
```

## `trace_function` — decorator

Traces every call of the decorated function (the function itself is added to `target_functions`).

```python
from focustracer import trace_function


@trace_function(output_file="output/compute.xml", detail_level="detailed")
def compute(x):
    return x * 2


compute(21)
```

## `TraceRecorder` — manual control

```python
from focustracer import TraceRecorder

recorder = TraceRecorder(output_file="output/manual.xml", target_functions=["process"])
recorder.start()
process([1, 2, 3])
recorder.stop()
recorder.save()              # format from output_format (default "xml")
recorder.save(format="json") # or "jsonl"
```

## Parameters

`TraceContext(**kwargs)` and `trace_function(**kwargs)` forward their arguments to `TraceRecorder`.

| Parameter | Default | Description |
|---|---|---|
| `output_file` | – | Trace output path |
| `target_functions` | – | Functions that activate tracing |
| `target_files` / `target_lines` / `target_thread_names` / `target_threads` | – | Filters inside activated scopes |
| `manifest` | – | A `TargetManifest` instead of the individual target lists |
| `detail_level` | `"normal"` | `minimal`, `normal`, `detailed` |
| `schema_version` | `"2.3"` | Schema version written into the trace |
| `output_format` | `"xml"` | `xml`, `json`, `jsonl` |
| `enable_threading` | `False` | Record other threads too |
| `max_depth` | `100` | Maximum recorded call depth |
| `max_iterations` | – | Max iterations written per compacted loop |
| `track_variables` / `track_arguments` | `True` | Record local variables / call arguments |

> The programmatic default is `detail_level="normal"`, while the CLI default is `detailed`.
> Use `detail_level="detailed"` if you want to run `slice` or `explain` on the result.
