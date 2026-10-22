# Architecture — Module Map

```
src/focustracer/
├── cli.py              # all CLI commands
├── core/
│   ├── recorder.py     # trace capture, scope grouping, loop compaction, XML/JSON output
│   ├── patcher.py      # runtime monkey-patch activation of target callables
│   ├── targeting.py    # target manifest and code inventory
│   ├── loader.py       # load a saved trace
│   ├── display.py      # terminal rendering (load)
│   ├── schema.py       # schema helpers
│   ├── slicer.py       # backward dynamic slicing (data + control dependencies)
│   ├── explain.py      # value-annotated slice context + LLM root-cause explanation
│   ├── reverse.py      # reverse execution: state reconstruction and rewind
│   ├── replay.py       # replay cursor: forward/backward, step into/over/out, def-use
│   └── align.py        # trace alignment and distance
├── agent/
│   ├── base.py
│   ├── ollama_client.py    # Ollama health, model listing, target suggestion
│   └── opencode_client.py  # OpenCode CLI health and target suggestion
├── validate/validator.py   # XML/XSD validation
├── gui/                    # FastAPI server + pre-built web frontend (frontend/dist)
└── schema/                 # packaged XSD / JSON schemas
```

## Pipeline

1. **Targeting** — manual flags and/or LLM suggestions are merged into a `TargetManifest`.
2. **Activation** — `patcher.py` wraps the target callables; tracing is active only inside their calls.
3. **Recording** — `recorder.py` records events per scope, compacts loops and writes the XML trace.
4. **Validation** — the trace is validated against the XSD.
5. **Analysis** — `slicer`, `explain`, `reverse`, `replay` and `align` work on the saved trace.
