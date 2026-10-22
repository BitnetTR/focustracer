# LLM Agents (Ollama / OpenCode)

An LLM is only needed for:

- `suggest-targets` and `run --auto-targets` — choosing which functions to trace
- `explain` — root-cause explanation of a slice

Everything else works offline.

| Agent | Flag | Default |
|---|---|---|
| Ollama (local) | `--agent ollama` | default agent, model `qwen2.5:3b`, URL `http://localhost:11434` |
| OpenCode CLI | `--agent opencode` | command `opencode` |

## Ollama

```bash
ollama serve
ollama pull qwen2.5:3b
python -m focustracer check-agent --agent ollama --model qwen2.5:3b
```

Then, for example:

```bash
python -m focustracer suggest-targets \
  --agent ollama --model qwen2.5:3b \
  --project-root tests/fixtures \
  --target-script tests/fixtures/cli_sample_app.py \
  --hint "Trace the worker path and multiplication logic"
```

Remote Ollama: pass `--ollama-url http://<host>:11434`.

Models can also be pulled from the web UI: **Settings › AI Agent › Models** (live progress),
or via `python -m focustracer install --agent ollama`.

## OpenCode

```bash
python -m focustracer check-agent --agent opencode --model opencode/minimax-m2.5-free --opencode-cmd opencode
```

## How target selection behaves

- `suggest-targets` fails fast if `--model` is not available in Ollama.
- Ollama is asked for JSON-mode output; if the first answer is ambiguous, FocusTracer retries once
  with a compact candidate list.
- Non-strict JSON or extra prose is handled with robust parsing, and an inventory-based fallback
  selection is used instead of returning an empty manifest.
- Even if `--project-root` is too narrow, `--target-script` is parsed directly so at least the
  script's own functions can be selected.
- Manual targets (`--function`, `--file`, …) and AI targets are merged with union semantics.
