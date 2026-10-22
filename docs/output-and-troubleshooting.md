# Output Files & Troubleshooting

## Where files are written

| Command | Output |
|---|---|
| `run --output path.xml` | Trace at `path.xml` |
| `run` (no `--output`) | `<--output-dir>/YYYYmmdd_HHMMSS_<script>.xml` (default dir `output/`) |
| `run` (always) | Merged target manifest next to the trace: `<trace>.targets.json` |
| `suggest-targets` | Nothing — manifest JSON printed to stdout |
| `suggest-targets --save-manifest` | Timestamped `.targets.json` under `--output-dir` |
| `suggest-targets --manifest-output p.json` | Manifest at `p.json` |
| `suggest-targets --execute` | Trace at `--trace-output`, or auto-named under `--trace-output-dir` |
| `slice` | `<trace>.sliced.xml` (or `--output`) |
| `explain --output f.md` | Explanation text |
| `reverse` / `replay` / `align --json p.json` | JSON sidecar |

The default trace format is XML. From Python, `TraceRecorder.save(format="json" | "jsonl")` is also available.

## Defaults

| Setting | Default |
|---|---|
| Agent / model | `ollama` / `qwen2.5:3b` |
| Schema version | `2.3` |
| CLI detail level | `detailed` |
| Target merge | union of manual and AI targets |

## Schemas

XSD / JSON schemas live in [`schema/`](../schema) (also packaged in `focustracer/schema/`):
`trace_schema_v1.xsd`, `v2`, `v2.1`, `v2.2`, `v2.3` and `trace_schema.json`.
Slicing (`slice`, `explain`) needs schema ≥ 2.3 and `detailed` traces.

## Troubleshooting

| Symptom | What to do |
|---|---|
| No trace file is produced | Pass an explicit `--output` path. |
| Trace is huge | Name specific `--function` targets, lower `--max-depth`, set `--max-iterations`. |
| `--auto-targets` finds nothing | Run `suggest-targets` to inspect the suggestion, or give `--function` manually. |
| Ollama connection errors | Run `check-agent` first; make sure `ollama serve` is running and the model is pulled. |
| `slice` / `explain` refuses the trace | Re-record with `--detail detailed` and schema 2.3 (the `run` defaults). |
| XML validation fails | Re-run with `--skip-validate`, then validate the XML manually against the XSD in `schema/`. |
