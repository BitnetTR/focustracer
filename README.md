# FocusTracer

FocusTracer is a zero-touch dynamic slicing and XML trace pipeline for AI-assisted Python debugging.
It runs a Python script, records a focused execution trace of the functions you care about
(chosen by you or by an LLM), and then lets you slice, rewind, replay, compare and explain that trace.

Türkçe kullanım kılavuzu: [README.tr.md](./README.tr.md)

| 🎥 AI4Sweng - FocusTracer (Bölüm 1) | 🚀 AI4Sweng - FocusTracer (Bölüm 2) |
| :---: | :---: |
| [![Bölüm 1](https://img.youtube.com/vi/XoAJj4MXodw/hqdefault.jpg)](https://www.youtube.com/watch?v=XoAJj4MXodw) | [![Bölüm 2](https://img.youtube.com/vi/P0XSIVUeN_Y/hqdefault.jpg)](https://www.youtube.com/watch?v=P0XSIVUeN_Y) |

<div align="center">
  <a href="./docs/FocusTracer_Sunum.pptx">
    <img width="500" src="https://github.com/user-attachments/assets/b89d0e92-3f80-48ea-9269-730be880a10e" alt="FocusTracer presentation">
  </a>
</div>

## Features

| Capability | Command | What it does |
|---|---|---|
| Trace capture | `run` | Runs a script and writes a schema-validated XML trace of the target functions |
| LLM targeting | `suggest-targets`, `run --auto-targets` | Asks a local (Ollama) or OpenCode model which functions to trace |
| Post-mortem view | `load` | Prints a saved trace as an execution tree / statistics table |
| Dynamic slicing | `slice` | Backward dynamic slice (data + control dependencies) from a crash or a value |
| Root-cause explanation | `explain` | Sends the slice (not the raw trace) to an LLM and gets cause + fix |
| Reverse execution | `reverse` | Reconstructs state at a point and rewinds backward |
| Interactive replay | `replay` | Movable cursor: step forward/backward, step into/over/out, def-use |
| Trace alignment | `align` | Aligns two traces of the same program and reports their distance |
| Web UI | `gui` | All of the above in a browser |

## Installation

Requires **Python 3.10+**. FocusTracer is not on PyPI; install it directly from GitHub:

```bash
pip install "git+https://github.com/BitnetTR/focustracer.git"
```

Pin to a branch, tag or commit with `@<ref>`:

```bash
pip install "git+https://github.com/BitnetTR/focustracer.git@master"
```

As a dependency of another project (`requirements.txt` or `pyproject.toml`):

```text
focustracer @ git+https://github.com/BitnetTR/focustracer.git@master
```

For development from a local clone:

```bash
git clone https://github.com/BitnetTR/focustracer.git
cd focustracer
pip install -e .
```

Editable installs straight from git, SSH access, upgrading and troubleshooting are covered in
**[docs/installation.md](./docs/installation.md)**.

Check the install:

```bash
focustracer --help
```

> `focustracer ...` and `python -m focustracer ...` are equivalent. The examples use `python -m focustracer`.

## Quick Start

```bash
# 1. (Optional) check that the LLM backend is reachable — only needed for AI features
python -m focustracer check-agent --agent ollama --model qwen2.5:3b

# 2. Trace a script (no --function = trace every function defined in the script)
python -m focustracer run --target-script app.py --output output/app_trace.xml

# 3. Find the root cause of the crash
python -m focustracer slice   output/app_trace.xml --at-exception
python -m focustracer explain output/app_trace.xml --at-exception --model qwen2.5:3b

# 4. Or open everything in the browser
python -m focustracer gui
```

From Python code:

```python
from focustracer import TraceContext

with TraceContext(output_file="output/programmatic.xml", target_functions=["process"]):
    process([1, 2, 3])
```

## Documentation

| Document | Content |
|---|---|
| [docs/installation.md](./docs/installation.md) | All install options (git, editable, SSH, pinning, upgrade) |
| [docs/cli.md](./docs/cli.md) | Every CLI command with all parameters and examples |
| [docs/llm-agents.md](./docs/llm-agents.md) | Ollama / OpenCode setup and target-selection behaviour |
| [docs/programmatic-usage.md](./docs/programmatic-usage.md) | `TraceContext`, `TraceRecorder`, `trace_function` |
| [docs/output-and-troubleshooting.md](./docs/output-and-troubleshooting.md) | Output files, schema versions, troubleshooting |
| [docs/architecture.md](./docs/architecture.md) | Module map |
| [CHANGELOG.md](./CHANGELOG.md) | Release history |
| [README.tr.md](./README.tr.md) | Türkçe kullanım kılavuzu |

## License

Apache License 2.0 — see [LICENSE](./LICENSE).
