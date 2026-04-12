"""FocusTracer GUI — FastAPI backend server."""
from __future__ import annotations

import asyncio
import json
import platform
import queue
import runpy
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from focustracer.agent.ollama_client import OllamaClient
from focustracer.agent.opencode_client import OpenCodeClient
from focustracer.core.patcher import DynamicPatcher
from focustracer.core.recorder import TraceContext, TraceRecorder
from focustracer.core.targeting import TargetManifest, build_code_inventory
from focustracer.gui.settings import add_recent_project, load_settings, save_settings

app = FastAPI(title="FocusTracer GUI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store ────────────────────────────────────────────────────────
_jobs: dict[str, dict[str, Any]] = {}


def _new_job() -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "log": [],
        "queue": queue.Queue(),
        "result": None,
    }
    return job_id


def _push(job_id: str, msg: str, kind: str = "info") -> None:
    entry = {"kind": kind, "message": msg, "ts": datetime.now().isoformat()}
    _jobs[job_id]["log"].append(entry)
    try:
        _jobs[job_id]["queue"].put_nowait(entry)
    except Exception:
        pass


# ── Helper: build agent ────────────────────────────────────────────────────────
def _build_agent(settings: dict[str, Any]):
    agent_name = settings.get("agent", "ollama")
    model = settings.get("model", "qwen2.5:3b")
    if agent_name == "opencode":
        # Force the constrained model for OpenCode as requested
        return OpenCodeClient(
            model="opencode/minimax-m2.5-free", 
            opencode_cmd=settings.get("opencode_cmd", "opencode")
        )
    return OllamaClient(model=model, base_url=settings.get("ollama_url", "http://localhost:11434"))


# ═══════════════════════════════════════════════════════════════════════════════
# Settings endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return load_settings()


class SettingsUpdate(BaseModel):
    agent: str | None = None
    model: str | None = None
    ollama_url: str | None = None
    opencode_cmd: str | None = None


@app.post("/api/settings")
def post_settings(body: SettingsUpdate) -> dict[str, Any]:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return save_settings(updates)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent status
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/agents/status")
def agents_status() -> dict[str, Any]:
    settings = load_settings()
    ollama = OllamaClient(
        model=settings["model"], base_url=settings["ollama_url"]
    ).health()
    opencode = OpenCodeClient(
        model=settings["model"], opencode_cmd=settings["opencode_cmd"]
    ).health()
    return {"ollama": ollama, "opencode": opencode}


# ═══════════════════════════════════════════════════════════════════════════════
# Hardware / system info
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/system/info")
def system_info() -> dict[str, Any]:
    """Return CPU, RAM, GPU and Python runtime information."""
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": {
            "name": platform.processor() or "unknown",
            "cores_physical": None,
            "cores_logical": None,
            "freq_mhz": None,
            "usage_percent": None,
        },
        "memory": {"total_gb": None, "available_gb": None, "used_percent": None},
        "gpu": [],
    }

    # psutil — optional
    try:
        import psutil
        cpu = info["cpu"]
        cpu["cores_physical"] = psutil.cpu_count(logical=False)
        cpu["cores_logical"] = psutil.cpu_count(logical=True)
        freq = psutil.cpu_freq()
        if freq:
            cpu["freq_mhz"] = round(freq.current, 1)
        cpu["usage_percent"] = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        info["memory"] = {
            "total_gb": round(mem.total / 1e9, 2),
            "available_gb": round(mem.available / 1e9, 2),
            "used_percent": mem.percent,
        }
    except ImportError:
        pass

    # GPUtil — optional
    try:
        import GPUtil  # type: ignore[import]
        for g in GPUtil.getGPUs():
            info["gpu"].append({
                "name": g.name,
                "vram_total_mb": round(g.memoryTotal),
                "vram_used_mb": round(g.memoryUsed),
                "load_percent": round(g.load * 100, 1),
                "temperature_c": g.temperature,
            })
    except (ImportError, Exception):
        pass

    # WMIC fallback for GPU name on Windows (no extra dep)
    if not info["gpu"] and sys.platform == "win32":
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=5
            )
            names = [ln.strip() for ln in result.stdout.splitlines() if ln.strip() and ln.strip().lower() != "name"]
            for name in names:
                info["gpu"].append({"name": name})
        except Exception:
            pass

    return info


@app.get("/api/ollama/metrics")
def ollama_metrics(model: str | None = None) -> dict[str, Any]:
    """Return token/s and energy estimate for current Ollama model via a tiny test prompt."""
    settings = load_settings()
    target_model = model or settings.get("model", "qwen2.5:3b")
    ollama_url = settings.get("ollama_url", "http://localhost:11434")

    try:
        import requests
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": target_model, "prompt": "Say: OK", "stream": False,
                  "options": {"num_predict": 5, "temperature": 0}},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        eval_count = data.get("eval_count", 0)          # tokens generated
        eval_duration_ns = data.get("eval_duration", 1)  # nanoseconds
        prompt_eval_count = data.get("prompt_eval_count", 0)
        prompt_eval_duration_ns = data.get("prompt_eval_duration", 1)

        tokens_per_sec = round(eval_count / (eval_duration_ns / 1e9), 2) if eval_duration_ns else 0
        prompt_tokens_per_sec = round(
            prompt_eval_count / (prompt_eval_duration_ns / 1e9), 2
        ) if prompt_eval_duration_ns else 0

        # Rough energy estimate: modern GPU ≈ 150W for inference
        # tokens_per_sec gives us utilisation proxy
        # Joules = Watts * seconds = 150 * (eval_count / tokens_per_sec)
        # This is intentionally labelled as an estimate.
        energy_j: float | None = None
        if tokens_per_sec > 0:
            energy_j = round(150 * (eval_count / tokens_per_sec), 4)

        return {
            "model": target_model,
            "tokens_per_sec": tokens_per_sec,
            "prompt_tokens_per_sec": prompt_tokens_per_sec,
            "eval_tokens": eval_count,
            "prompt_tokens": prompt_eval_count,
            "energy_j_estimate": energy_j,
            "energy_note": "Rough estimate assuming ~150W GPU power draw",
            "total_duration_ms": round(data.get("total_duration", 0) / 1e6, 1),
        }
    except Exception as exc:
        return {"error": str(exc), "model": target_model}


# ═══════════════════════════════════════════════════════════════════════════════
# Project / file endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/files")
def list_files(root: str = Query(...)) -> dict[str, Any]:
    """Return tree of Python files in *root*."""
    root_path = Path(root)
    if not root_path.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    add_recent_project(root)

    def _scan(path: Path, depth: int = 0) -> list[dict]:
        entries: list[dict] = []
        try:
            items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return entries
        for item in items:
            if item.name.startswith(".") or item.name in ("__pycache__", "node_modules", ".git", "myenv", "venv", ".venv"):
                continue
            if item.is_dir():
                children = _scan(item, depth + 1)
                if children or depth < 2:
                    entries.append({"name": item.name, "path": str(item), "type": "dir", "children": children})
            elif item.suffix == ".py":
                entries.append({"name": item.name, "path": str(item), "type": "file"})
        return entries

    tree = _scan(root_path)
    return {"root": root, "tree": tree}


@app.get("/api/file-content")
def file_content(path: str = Query(...)) -> dict[str, Any]:
    fp = Path(path)
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        text = fp.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"path": str(fp), "content": text}


@app.get("/api/inventory")
def get_inventory(root: str = Query(...), script: str = Query(...)) -> dict[str, Any]:
    try:
        inv = build_code_inventory(project_root=root, target_script=script)
        return inv.to_prompt_payload()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Output / trace log browser
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/api/outputs")
def list_outputs(project_root: str | None = None) -> dict[str, Any]:
    """List trace XML files from src/output/ (FocusTracer global output directory)."""
    # Always look in FocusTracer/src/output
    base = Path(__file__).resolve().parent.parent.parent / "output"
    candidates = [base]

    seen: set[str] = set()
    files = []
    for search_dir in candidates:
        if not search_dir.is_dir():
            continue
        for fp in sorted(search_dir.glob("*.xml"), reverse=True):
            key = str(fp.resolve())
            if key in seen:
                continue
            seen.add(key)
            targets_file = fp.with_suffix(".targets.json")
            targets = None
            if targets_file.exists():
                try:
                    targets = json.loads(targets_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            stat = fp.stat()
            files.append({
                "filename": fp.name,
                "path": str(fp),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "targets": targets,
            })

    # Sort combined list by modification time descending
    files.sort(key=lambda x: x["modified"], reverse=True)
    return {"outputs": files}


@app.get("/api/output")
def get_output(path: str = Query(...)) -> dict[str, Any]:
    fp = Path(path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = fp.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"path": str(fp), "content": content, "filename": fp.name}


# ═══════════════════════════════════════════════════════════════════════════════
# Trace execution
# ═══════════════════════════════════════════════════════════════════════════════

class RunTraceRequest(BaseModel):
    project_root: str
    target_script: str
    functions: list[str] = []
    files: list[str] = []
    lines: list[str] = []
    thread_names: list[str] = []
    detail: str = "detailed"
    max_depth: int = 100
    max_iterations: int | None = None
    schema_version: str = "2.1"
    output_dir: str = "output"


class SuggestRequest(BaseModel):
    project_root: str
    target_script: str
    hint: str | None = None
    error_context: str | None = None
    execute: bool = True
    detail: str = "detailed"
    max_depth: int = 100
    max_iterations: int | None = None
    schema_version: str = "2.1"
    output_dir: str = "output"
    # manual additions merged with AI suggestions
    functions: list[str] = []
    files: list[str] = []


def _resolve_output_path(
    target_script: str, output_dir: str, project_root: str | None = None
) -> tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_stem = Path(target_script).stem
    
    # Store globally in FocusTracer/src/output
    out_dir = Path(__file__).resolve().parent.parent.parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / f"{timestamp}_{script_stem}.xml"
    manifest_path = trace_path.with_suffix(".targets.json")
    return trace_path, manifest_path


def _runtime_manifest(manifest: TargetManifest, target_script: str) -> TargetManifest:
    script_stem = Path(target_script).stem
    runtime_functions: list[str] = []
    for fn in manifest.functions:
        runtime_functions.append(fn)
        parts = fn.split(".")
        if parts:
            runtime_functions.append(parts[-1])
        if len(parts) >= 2:
            runtime_functions.append(".".join(parts[-2:]))
        suffix = None
        if fn.startswith(f"{script_stem}."):
            suffix = fn[len(script_stem) + 1:]
        else:
            marker = f".{script_stem}."
            if marker in fn:
                suffix = fn.split(marker, 1)[1]
        if suffix:
            runtime_functions.append(f"__main__.{suffix}")
            runtime_functions.append(suffix)
    return TargetManifest(
        functions=runtime_functions,
        files=list(manifest.files),
        lines=list(manifest.lines),
        thread_names=list(manifest.thread_names),
    ).normalized()


def _run_trace_thread(job_id: str, req: RunTraceRequest) -> None:
    _push(job_id, "▶ Starting trace…")
    _jobs[job_id]["status"] = "running"

    try:
        merged = TargetManifest.from_cli(
            functions=req.functions,
            files=req.files,
            lines=req.lines,
            thread_names=req.thread_names,
        )
        if not merged.has_targets():
            _push(job_id, "❌ No targets specified.", kind="error")
            _jobs[job_id]["status"] = "error"
            return

        trace_path, manifest_path = _resolve_output_path(
            req.target_script, req.output_dir, req.project_root
        )
        _push(job_id, f"📁 Output dir: {trace_path.parent}")
        manifest_path.write_text(merged.to_json() + "\n", encoding="utf-8")

        runtime = _runtime_manifest(merged, req.target_script)
        _push(job_id, f"🎯 Targets: {merged.functions}")

        recorder = TraceRecorder(
            output_file=str(trace_path),
            output_format="xml",
            detail_level=req.detail,
            max_depth=req.max_depth,
            max_iterations=req.max_iterations,
            schema_version=req.schema_version,
            enable_threading=True,
            manifest=runtime,
        )

        patcher = DynamicPatcher(tracer=recorder, target_functions=merged.functions)
        patch_results = patcher.patch_all()
        patched = [t for t, ok in patch_results.items() if ok]
        if patched:
            _push(job_id, f"🔧 Patched: {sorted(patched)}")

        target_script_path = Path(req.target_script).resolve()
        # Add project root to sys.path so imports work
        project_root = Path(req.project_root).resolve()
        old_path = list(sys.path)
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        try:
            with TraceContext(recorder=recorder):
                runpy.run_path(str(target_script_path), run_name="__main__")
        finally:
            sys.path[:] = old_path
            patcher.unpatch_all()

        _push(job_id, f"✅ Trace saved → {trace_path.name}", kind="success")
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = {
            "trace_path": str(trace_path),
            "manifest_path": str(manifest_path),
            "filename": trace_path.name,
        }

    except Exception as exc:
        _push(job_id, f"❌ Error: {exc}", kind="error")
        _jobs[job_id]["status"] = "error"
    finally:
        try:
            _jobs[job_id]["queue"].put_nowait(None)  # sentinel
        except Exception:
            pass


def _suggest_trace_thread(job_id: str, req: SuggestRequest) -> None:
    _push(job_id, "🤖 Connecting to AI agent…")
    _jobs[job_id]["status"] = "running"

    try:
        settings = load_settings()
        agent = _build_agent(settings)

        health = agent.health()
        if not health.get("ok"):
            _push(job_id, f"❌ Agent not available: {health.get('error', 'unknown')}", kind="error")
            _jobs[job_id]["status"] = "error"
            return
        if not health.get("model_available"):
            _push(job_id, f"❌ Model not available: {settings.get('model')}", kind="error")
            _jobs[job_id]["status"] = "error"
            return

        _push(job_id, f"✅ Agent ready ({settings.get('agent')} / {settings.get('model')})")
        _push(job_id, "📋 Building code inventory…")

        inv = build_code_inventory(project_root=req.project_root, target_script=req.target_script)
        manual = TargetManifest.from_cli(functions=req.functions, files=req.files)

        payload = inv.to_prompt_payload()
        fn_count = len(payload.get("functions", []))
        _push(job_id, f"📊 Inventory: {fn_count} functions found")

        # Trim inventory to avoid overwhelming small models (token limit)
        MAX_FUNCTIONS = 80
        if fn_count > MAX_FUNCTIONS:
            _push(job_id, f"✂️  Trimming inventory to top {MAX_FUNCTIONS} functions (model token limit)")
            payload["functions"] = payload["functions"][:MAX_FUNCTIONS]

        _push(job_id, f"🔍 Asking AI to suggest targets (hint: {req.hint or 'none'})…")
        try:
            suggested_dict = agent.suggest_targets(
                payload,
                manual_targets=manual.to_dict(),
                error_context=req.error_context,
                user_hint=req.hint,
            )
        except Exception as agent_exc:
            tb = traceback.format_exc()
            _push(job_id, f"❌ AI agent error: {agent_exc}", kind="error")
            _push(job_id, f"🔍 Traceback: {tb[:800]}", kind="error")
            _jobs[job_id]["status"] = "error"
            return
        suggested = TargetManifest.from_dict(suggested_dict)
        merged = manual.merge(suggested)

        _push(job_id, f"🎯 AI selected: {merged.functions}")

        if not req.execute:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = {"manifest": merged.to_dict()}
            return

        if not merged.has_targets():
            _push(job_id, "❌ AI returned no targets.", kind="error")
            _jobs[job_id]["status"] = "error"
            return

        trace_path, manifest_path = _resolve_output_path(
            req.target_script, req.output_dir, req.project_root
        )
        _push(job_id, f"📁 Output dir: {trace_path.parent}")
        manifest_path.write_text(merged.to_json() + "\n", encoding="utf-8")

        runtime = _runtime_manifest(merged, req.target_script)
        recorder = TraceRecorder(
            output_file=str(trace_path),
            output_format="xml",
            detail_level=req.detail,
            max_depth=req.max_depth,
            max_iterations=req.max_iterations,
            schema_version=req.schema_version,
            enable_threading=True,
            manifest=runtime,
        )

        patcher = DynamicPatcher(tracer=recorder, target_functions=merged.functions)
        patch_results = patcher.patch_all()
        patched = [t for t, ok in patch_results.items() if ok]
        if patched:
            _push(job_id, f"🔧 Patched: {sorted(patched)}")

        project_root = Path(req.project_root).resolve()
        old_path = list(sys.path)
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        _push(job_id, "▶ Running target script…")
        try:
            with TraceContext(recorder=recorder):
                runpy.run_path(str(Path(req.target_script).resolve()), run_name="__main__")
        finally:
            sys.path[:] = old_path
            patcher.unpatch_all()

        _push(job_id, f"✅ Trace saved → {trace_path.name}", kind="success")
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = {
            "trace_path": str(trace_path),
            "manifest_path": str(manifest_path),
            "filename": trace_path.name,
            "manifest": merged.to_dict(),
        }

    except Exception as exc:
        _push(job_id, f"❌ Error: {exc}", kind="error")
        _jobs[job_id]["status"] = "error"
    finally:
        try:
            _jobs[job_id]["queue"].put_nowait(None)
        except Exception:
            pass


@app.post("/api/trace/run")
def start_run_trace(req: RunTraceRequest) -> dict[str, str]:
    job_id = _new_job()
    t = threading.Thread(target=_run_trace_thread, args=(job_id, req), daemon=True)
    t.start()
    return {"job_id": job_id}


@app.post("/api/trace/suggest")
def start_suggest_trace(req: SuggestRequest) -> dict[str, str]:
    job_id = _new_job()
    t = threading.Thread(target=_suggest_trace_thread, args=(job_id, req), daemon=True)
    t.start()
    return {"job_id": job_id}


@app.get("/api/trace/stream/{job_id}")
async def stream_trace(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def generator() -> AsyncGenerator[dict, None]:
        q: queue.Queue = _jobs[job_id]["queue"]
        # replay existing log entries first
        for entry in list(_jobs[job_id].get("log", [])):
            yield {"data": json.dumps(entry)}
            await asyncio.sleep(0)

        while True:
            try:
                item = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=30)
                )
            except Exception:
                break
            if item is None:
                break
            yield {"data": json.dumps(item)}
            await asyncio.sleep(0)

        # Send final status
        status = _jobs[job_id]["status"]
        result = _jobs[job_id].get("result")
        yield {"data": json.dumps({"kind": "done", "status": status, "result": result})}

    return EventSourceResponse(generator())


@app.get("/api/job/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    return {"job_id": job_id, "status": job["status"], "log": job["log"], "result": job.get("result")}


# ═══════════════════════════════════════════════════════════════════════════════
# Static files (React build)
# ═══════════════════════════════════════════════════════════════════════════════

_FRONTEND_BUILD = Path(__file__).parent / "frontend" / "dist"


def _mount_static() -> None:
    if _FRONTEND_BUILD.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_FRONTEND_BUILD / "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            index = _FRONTEND_BUILD / "index.html"
            if index.exists():
                return HTMLResponse(index.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>Frontend not built yet. Run: npm run build inside gui/frontend.</h1>")


_mount_static()
