# FocusTracer AI Suggestion Architecture (GUI / CLI Integration)

FocusTracer leverages Large Language Models (LLMs) to automatically suggest which functions and classes to trace, drastically reducing the time spent navigating unfamiliar codebases. This document answers common questions on how the AI suggestion mechanism works, both strictly on the backend and how it seamlessly reflects onto the Frontend GUI.

---

## 1. How does the AI know what to suggest? (Code Inventory)

Before the AI is called, FocusTracer runs an AST (Abstract Syntax Tree) scan on your targeted `project_root`. It maps out:
- Available files (e.g., `main.py`, `utils.py`)
- Defined functions and their docstrings.
- Defined classes and their methods.

These findings are aggregated into a `CodeInventory`. Because LLMs (especially local smaller ones) possess tight token limits, a safety mechanism kicks in: **If your project contains more than 80 functions, the system intelligently truncates the list down to the most significant 80 functions** before sending the payload. This entirely eliminates the `Trace failed` crash linked to token context overload.

## 2. Does the AI run CLI Commands directly? (Terminal Access)

**No.** The underlying LLMs (`ollama` or `opencode`) **do not** interact with or control the terminal. 

FocusTracer was designed with the AI only acting as the *Advisor*. When you execute a trace in the GUI or CLI:
1. The AI reads the truncated `CodeInventory` and the error hint.
2. The AI returns a JSON response strictly containing the logical names of the targets it suggests (e.g., `['utils.calculate_total', 'main.process_payment']`).
3. FocusTracer's internal backend logic reads this JSON, patches these specific targets using Python's `sys.settrace`, and then *FocusTracer* itself executes the script.

## 3. How does the Suggest output reflect on the GUI? (Server-Sent Events)

Since an AI generation request can take anywhere from 2 seconds to a minute (depending heavily on hardware and the model size), standard HTTP polling is inefficient. FocusTracer uses **Server-Sent Events (SSE)**.

When you click "Run Trace" in the GUI:
1. The React frontend sends a `POST` request, and the FastAPI backend assigns an instantaneous `Job ID`.
2. The UI immediately opens an `EventSource` stream subscribing to `/api/job/{job_id}/stream`.
3. The server runs the AI agent in a background thread and streams distinct `_push(job_id, message)` logs back to the browser in real-time. 

You actually see the process step-by-step:
- `🤖 Connecting to AI agent…`
- `📋 Building code inventory…`
- `✂️ Trimming inventory to top 80 functions`
- `🔍 Asking AI to suggest targets…`
- `🎯 AI selected: [...]`

This ensures that the user is never left wondering if the CLI failed or is stuck.

## 4. Where do the generated traces go? (Strict Output Isolation)

We've abandoned resolving the trace location dynamically to the interpreted Python application's own directory. Now, **all Trace logs are strictly saved underneath FocusTracer's global directory:**
`c:\Users\Yasin\Desktop\FocusTracer\src\output\`

This ensures trace logs (`*.xml` and manifest metadata) don't pollute your testing projects folders.

## 5. Model Specifications and Agent Quirks

Users can utilize two distinct agents:
- **Ollama**: For standard local LLMs (`qwen2.5:3b`, `llama3`). Supports hardware benchmarks via `/api/ollama/metrics`.
- **OpenCode**: A dedicated code-assistant interface. The models differ strictly from Ollama variants. **When using OpenCode in the Settings, the only officially tested generic model string is `opencode/minimax-m2.5-free`.** Ensure you update this in the UI Settings -> "Model Name" to avoid execution failures.

---
*Created per explicit FocusTracer development architecture goals. For debugging GUI agent streams, check the Network tab -> EventStream.*
