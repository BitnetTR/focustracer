from __future__ import annotations

import argparse
import json
import runpy
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from focustracer.agent.base import BaseAIAgent
from focustracer.agent.opencode_client import OpenCodeClient
from focustracer.agent.ollama_client import OllamaClient
from focustracer.core.patcher import DynamicPatcher
from focustracer.core.recorder import TraceContext, TraceRecorder
from focustracer.core.targeting import TargetManifest, build_code_inventory

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.table import Table

    HAS_RICH = True
except Exception:  # pragma: no cover - fallback path
    Console = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Prompt = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    HAS_RICH = False


DEFAULT_MODEL = "qwen2.5:3b"
INSTALL_CONSOLE = Console() if HAS_RICH else None


def _install_ask(prompt_text: str, default: str | None = None) -> str:
    if HAS_RICH and Prompt is not None:
        return Prompt.ask(prompt_text, default=default)
    value = input(f"{prompt_text}: ").strip()
    if not value and default is not None:
        return default
    return value


def _install_echo(message: str = "") -> None:
    if HAS_RICH and INSTALL_CONSOLE is not None:
        INSTALL_CONSOLE.print(message)
        return
    print(message)


def _build_agent(
    agent_name: str,
    model: str,
    base_url: str,
    opencode_cmd: str,
) -> BaseAIAgent:
    if agent_name == "ollama":
        return OllamaClient(model=model, base_url=base_url)
    if agent_name == "opencode":
        return OpenCodeClient(model=model, opencode_cmd=opencode_cmd)
    raise ValueError(f"Unsupported agent: {agent_name}")


def _add_target_arguments(parser: argparse.ArgumentParser) -> None:
    """ Target specification arguments for both suggest-targets and run commands 
    TR: Target belirlemek için gerekli olan argümanları ekler. Hem suggest-targets hem de run komutlarında kullanılır.
     - --function: Belirli fonksiyonları hedeflemek için kullanılır. Qualified function isimleri sağlanır (örneğin, module.submodule.function).
     - --file: Belirli dosyaları hedeflemek için kullanılır. Göreli veya mutlak dosya yolları sağlanır.
     - --line: Belirli satırları hedeflemek için kullanılır. Dosya yolu ve satır numarası şeklinde sağlanır (örneğin, path/to/file.py:42).
     - --thread-name: Belirli thread'leri hedeflemek için kullanılır. Thread isimleri sağlanır. Bu, aktif scope'lar içindeki thread'leri filtrelemek için kullanılabilir.
        Bu argümanlar, manuel olarak hedef belirlemek isteyen kullanıcılar için esneklik sağlar. LLM tarafından önerilen hedeflerle birleştirilebilir veya tek başına kullanılabilirler.
    """
    
    parser.add_argument(
        "--function", 
        action="append", 
        default=[], 
        help="Qualified function target"
    )
    parser.add_argument(
        "--file", 
        action="append", 
        default=[], 
        help="Relative or absolute file filter"
    )
    parser.add_argument(
        "--line",
        action="append",
        default=[],
        help="Line filter in the form path/to/file.py:42",
    )
    parser.add_argument(
        "--thread-name",
        action="append",
        default=[],
        help="Thread name filter inside activated scopes",
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="focustracer",
        description="FocusTracer - LLM-guided dynamic slicing and XML tracing",
    )
    subparsers = parser.add_subparsers(dest="command")

    gui_parser = subparsers.add_parser("gui", help="Launch the FocusTracer web UI")
    gui_parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    gui_parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    gui_parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")

    install_parser = subparsers.add_parser("install", help="Install and manage AI agents")
    install_parser.add_argument("--agent", choices=["ollama", "opencode"], help="Open a specific installer flow")
    install_parser.add_argument("--model", default=DEFAULT_MODEL, help="Model used for status checks and Ollama pulls")
    install_parser.add_argument("--status", action="store_true", help="Show status snapshot and exit")
    install_parser.add_argument("--ollama-url", default="http://localhost:11434")
    install_parser.add_argument("--opencode-cmd", default="opencode")

    check_parser = subparsers.add_parser("check-agent", help="Check agent connectivity")
    check_parser.add_argument(
        "--agent", 
        choices=["ollama", "opencode"], 
        default="ollama"
    )
    check_parser.add_argument("--model", default=DEFAULT_MODEL)
    check_parser.add_argument("--ollama-url", default="http://localhost:11434")
    check_parser.add_argument("--opencode-cmd", default="opencode")

    suggest_parser = subparsers.add_parser(
        "suggest-targets", help="Ask the LLM for targets"
    )
    suggest_parser.add_argument(
        "--agent", choices=["ollama", "opencode"], default="ollama"
    )
    suggest_parser.add_argument("--model", default=DEFAULT_MODEL)
    suggest_parser.add_argument("--ollama-url", default="http://localhost:11434")
    suggest_parser.add_argument("--opencode-cmd", default="opencode")
    suggest_parser.add_argument("--project-root", required=True)
    suggest_parser.add_argument("--target-script", required=True)
    suggest_parser.add_argument("--hint", help="Extra user hint for target selection")
    suggest_parser.add_argument("--error-context", help="Optional error/log context")
    suggest_parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute tracing immediately using merged suggested targets",
    )
    suggest_parser.add_argument(
        "--manifest-output",
        help="Optional path to write suggested target manifest JSON",
    )
    suggest_parser.add_argument(
        "--save-manifest",
        action="store_true",
        help="Write suggested target manifest into output dir with timestamped name",
    )
    suggest_parser.add_argument("--output-dir", default="output")
    suggest_parser.add_argument(
        "--trace-output", help="Trace XML output path when --execute is used"
    )
    suggest_parser.add_argument(
        "--trace-output-dir",
        default="output",
        help="Trace output directory when --execute is used and --trace-output is not provided",
    )
    suggest_parser.add_argument("--schema-version", default="2.3")
    suggest_parser.add_argument(
        "--detail", choices=["minimal", "normal", "detailed"], default="detailed"
    )
    suggest_parser.add_argument("--max-depth", type=int, default=100)
    suggest_parser.add_argument(
        "--max-iterations", type=int, help="Limit iterations written per compacted loop"
    )
    suggest_parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip post-run XML structural validation when --execute is used",
    )
    _add_target_arguments(suggest_parser)

    run_parser = subparsers.add_parser("run", help="Run tracing")
    run_parser.add_argument("--agent", choices=["ollama", "opencode"], default="ollama")
    run_parser.add_argument("--model", default=DEFAULT_MODEL)
    run_parser.add_argument("--ollama-url", default="http://localhost:11434")
    run_parser.add_argument("--opencode-cmd", default="opencode")
    run_parser.add_argument(
        "--project-root",
        help="Project root to inventory; defaults to target script dir",
    )
    run_parser.add_argument("--target-script", required=True)
    run_parser.add_argument("--hint", help="Extra user hint for target selection")
    run_parser.add_argument("--error-context", help="Optional error/log context")
    run_parser.add_argument(
        "--auto-targets", action="store_true", help="Request AI target suggestions"
    )
    run_parser.add_argument("--output", help="Trace XML output path")
    run_parser.add_argument("--output-dir", default="output")
    run_parser.add_argument("--schema-version", default="2.3")
    run_parser.add_argument(
        "--detail", choices=["minimal", "normal", "detailed"], default="detailed"
    )
    run_parser.add_argument("--max-depth", type=int, default=100)
    run_parser.add_argument(
        "--max-iterations", type=int, help="Limit iterations written per compacted loop"
    )
    run_parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip post-run XML structural validation",
    )
    _add_target_arguments(run_parser)

    load_parser = subparsers.add_parser(
        "load",
        help="Load and display a saved trace XML (post-mortem debugging)",
    )
    load_parser.add_argument(
        "trace_file",
        help="Path to the trace XML file to load",
    )
    load_parser.add_argument(
        "--summary",
        action="store_true",
        help="Show only statistics table, skip the execution tree",
    )
    load_parser.add_argument(
        "--filter-function",
        default=None,
        metavar="NAME",
        help="Only show scopes matching this function name",
    )
    load_parser.add_argument(
        "--filter-thread",
        default=None,
        metavar="ID_OR_NAME",
        help="Only show events from this thread ID or name",
    )
    load_parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip XSD validation before displaying",
    )

    # ------------------------------------------------------------------ slice
    slice_parser = subparsers.add_parser(
        "slice",
        help="Compute a backward dynamic slice over a saved trace (v2.3)",
    )
    slice_parser.add_argument(
        "trace_file",
        help="Path to the trace XML file (must be detailed, schema >= 2.3)",
    )
    slice_parser.add_argument(
        "--at-exception",
        action="store_true",
        help="Slice from the innermost exception's failing line (default if no --at)",
    )
    slice_parser.add_argument(
        "--at",
        default=None,
        metavar="[FILE:]LINE[:VAR]",
        help="Slice criterion, e.g. app.py:42:total or 42:total",
    )
    slice_parser.add_argument(
        "--no-control",
        action="store_true",
        help="Data dependencies only (skip control dependencies)",
    )
    slice_parser.add_argument(
        "--output",
        default=None,
        help="Sliced XML output path (default: <trace>.sliced.xml next to input)",
    )
    slice_parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip XSD validation of the sliced output",
    )

    # ---------------------------------------------------------------- explain
    explain_parser = subparsers.add_parser(
        "explain",
        help="LLM root-cause explanation from a backward dynamic slice",
    )
    explain_parser.add_argument(
        "trace_file",
        help="Path to the trace XML file (detailed, schema >= 2.3)",
    )
    explain_parser.add_argument("--agent", choices=["ollama", "opencode"], default="ollama")
    explain_parser.add_argument("--model", default=DEFAULT_MODEL)
    explain_parser.add_argument("--ollama-url", default="http://localhost:11434")
    explain_parser.add_argument("--opencode-cmd", default="opencode")
    explain_parser.add_argument(
        "--at-exception",
        action="store_true",
        help="Explain the innermost exception (default if no --at)",
    )
    explain_parser.add_argument(
        "--at", default=None, metavar="[FILE:]LINE[:VAR]",
        help="Slice criterion, e.g. app.py:42:total",
    )
    explain_parser.add_argument(
        "--no-control", action="store_true", help="Data dependencies only",
    )
    explain_parser.add_argument(
        "--error-context", default=None, help="Extra context passed to the model",
    )
    explain_parser.add_argument(
        "--show-context", action="store_true",
        help="Print the exact slice context sent to the model",
    )
    explain_parser.add_argument(
        "--output", default=None, help="Write the explanation to this file",
    )

    # ---------------------------------------------------------------- reverse
    reverse_parser = subparsers.add_parser(
        "reverse",
        help="Reverse execution: reconstruct state and step backward through a trace",
    )
    reverse_parser.add_argument("trace_file", help="Path to the trace XML file")
    reverse_parser.add_argument(
        "--at-exception", action="store_true",
        help="Reconstruct state at the crash (default if no --at-event/--at-line)",
    )
    reverse_parser.add_argument(
        "--at-event", type=int, default=None, metavar="ID",
        help="Reconstruct state at line event ID",
    )
    reverse_parser.add_argument(
        "--at-line", type=int, default=None, metavar="LINE",
        help="Reconstruct state at a source line",
    )
    reverse_parser.add_argument(
        "--function", default=None, help="Disambiguate --at-line by function",
    )
    reverse_parser.add_argument(
        "--step-back", type=int, default=5, metavar="K",
        help="How many line-events to rewind from the target (default 5)",
    )
    reverse_parser.add_argument(
        "--json", default=None, metavar="PATH",
        help="Write the reconstructed state(s) to a JSON sidecar",
    )

    # ---------------------------------------------------------------- replay
    replay_parser = subparsers.add_parser(
        "replay",
        help="Interactive replay: step forward AND backward through a trace, inspect state at any point",
    )
    replay_parser.add_argument("trace_file", help="Path to the trace XML file")
    replay_parser.add_argument(
        "--at-exception", action="store_true",
        help="Start the cursor at the crash",
    )
    replay_parser.add_argument(
        "--at-event", type=int, default=None, metavar="ID",
        help="Start the cursor at line event ID",
    )
    replay_parser.add_argument(
        "--at-line", type=int, default=None, metavar="LINE",
        help="Start the cursor at a source line",
    )
    replay_parser.add_argument(
        "--seq", type=int, default=None, metavar="N",
        help="Start the cursor at timeline index N (0 = first line event)",
    )
    replay_parser.add_argument(
        "--function", default=None, help="Disambiguate --at-line by function",
    )
    replay_parser.add_argument(
        "--step", type=int, default=0, metavar="N",
        help="Move N steps from the start point: +N forward, -N backward",
    )
    replay_step = replay_parser.add_mutually_exclusive_group()
    replay_step.add_argument("--into", action="store_true", help="Debugger step into (one line, enters calls)")
    replay_step.add_argument("--over", action="store_true", help="Debugger step over (skip called frames)")
    replay_step.add_argument("--out", action="store_true", help="Debugger step out (leave current frame)")
    replay_parser.add_argument(
        "--back", action="store_true",
        help="Apply --into/--over/--out backward (reverse execution)",
    )
    replay_parser.add_argument(
        "--window", type=int, default=3, metavar="K",
        help="How many neighbour line-events to show around the cursor (default 3)",
    )
    replay_parser.add_argument(
        "--def", dest="def_var", default=None, metavar="VAR",
        help="Show which statement last defined VAR at the cursor (def-use)",
    )
    replay_parser.add_argument(
        "--list", action="store_true",
        help="Print the whole navigable timeline instead of a single cursor view",
    )
    replay_parser.add_argument(
        "--json", default=None, metavar="PATH",
        help="Write the cursor view (state + neighbours) to a JSON sidecar",
    )

    # ---------------------------------------------------------------- align
    align_parser = subparsers.add_parser(
        "align",
        help="Align traces of the same program: distance, divergences, side-by-side replay",
    )
    align_parser.add_argument(
        "traces", nargs="+", metavar="TRACE",
        help="Two traces to align, or 3+ to curate them as a trace set",
    )
    align_parser.add_argument(
        "--show-alignment", action="store_true",
        help="Print the aligned statement pairs (matches and gaps)",
    )
    align_parser.add_argument(
        "--divergences", action="store_true",
        help="Print the divergence regions (contiguous runs of gaps)",
    )
    align_parser.add_argument(
        "--json", default=None, metavar="PATH",
        help="Write the alignment / trace-set summary to a JSON sidecar",
    )
    # -- side-by-side navigation: move a cursor on A, read the aligned B ----
    align_nav = align_parser.add_argument_group(
        "side-by-side navigation",
        "Move a cursor through trace A and read the aligned point in trace B "
        "(two traces only). Mirrors the `replay` start-point and step options.",
    )
    align_nav.add_argument(
        "--seq", type=int, default=None, metavar="N",
        help="Start A's cursor at timeline index N",
    )
    align_nav.add_argument(
        "--at-event", type=int, default=None, metavar="ID",
        help="Start A's cursor at line event ID",
    )
    align_nav.add_argument(
        "--at-line", type=int, default=None, metavar="LINE",
        help="Start A's cursor at a source line",
    )
    align_nav.add_argument(
        "--at-exception", action="store_true",
        help="Start A's cursor at the crash",
    )
    align_nav.add_argument(
        "--function", default=None, help="Disambiguate --at-line by function",
    )
    align_nav.add_argument(
        "--step", type=int, default=0, metavar="N",
        help="Move N steps from the start point: +N forward, -N backward",
    )
    align_step = align_nav.add_mutually_exclusive_group()
    align_step.add_argument("--into", action="store_true", help="Debugger step into on A")
    align_step.add_argument("--over", action="store_true", help="Debugger step over on A")
    align_step.add_argument("--out", action="store_true", help="Debugger step out on A")
    align_nav.add_argument(
        "--back", action="store_true", help="Apply --into/--over/--out backward",
    )
    align_nav.add_argument(
        "--window", type=int, default=3, metavar="K",
        help="Neighbour line-events to show around each cursor (default 3)",
    )

    return parser


def _check_ollama_status(ollama_url: str = "http://localhost:11434", model: str = DEFAULT_MODEL) -> dict:
    """Ollama kurulum durumunu kontrol et."""
    try:
        client = OllamaClient(model=model, base_url=ollama_url)
        health = client.health()
        return {
            "installed": health.get("ok", False),
            "health": health,
            "models": health.get("available_models", [])
        }
    except Exception as e:
        return {
            "installed": False,
            "health": {"ok": False, "error": str(e)},
            "models": []
        }


def _check_opencode_status(opencode_cmd: str = "opencode", model: str = DEFAULT_MODEL) -> dict:
    """OpenCode kurulum durumunu kontrol et.

    Fallback order:
    1) configured command (default: opencode)
    2) python -m opencode
    3) py -m opencode
    """
    candidates: list[str] = []
    for candidate in [opencode_cmd, "python -m opencode", "py -m opencode"]:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    attempts: list[dict[str, str | bool | None]] = []
    for candidate in candidates:
        try:
            client = OpenCodeClient(model=model, opencode_cmd=candidate)
            health = client.health()
            attempts.append(
                {
                    "command": candidate,
                    "ok": bool(health.get("ok")),
                    "error": health.get("error"),
                }
            )
            if health.get("ok"):
                return {
                    "installed": True,
                    "health": health,
                    "version": health.get("version"),
                    "detected_command": candidate,
                    "attempts": attempts,
                }
        except Exception as exc:
            attempts.append({"command": candidate, "ok": False, "error": str(exc)})

    last_error = ""
    if attempts:
        raw_error = attempts[-1].get("error")
        last_error = str(raw_error) if raw_error else "OpenCode command not found"

    return {
        "installed": False,
        "health": {"ok": False, "error": last_error},
        "version": None,
        "detected_command": None,
        "attempts": attempts,
    }


def _print_status_panel(ollama_status: dict, opencode_status: dict) -> None:
    """Mevcut kurulum durumunu göster."""
    if HAS_RICH and INSTALL_CONSOLE is not None and Table is not None and Panel is not None:
        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("Agent", style="bold")
        table.add_column("Status")
        table.add_column("Details")

        ollama_models = ollama_status.get("models", [])
        if ollama_status.get("installed"):
            ollama_details = "Models: " + (", ".join(ollama_models[:5]) if ollama_models else "none")
            if len(ollama_models) > 5:
                ollama_details += f" (+{len(ollama_models) - 5} more)"
            table.add_row("Ollama", "[green]INSTALLED[/green]", ollama_details)
        else:
            err = ollama_status.get("health", {}).get("error", "Unknown error")
            table.add_row("Ollama", "[red]NOT INSTALLED[/red]", str(err))

        if opencode_status.get("installed"):
            version = opencode_status.get("version") or "unknown"
            cmd = opencode_status.get("detected_command") or "opencode"
            table.add_row("OpenCode", "[green]INSTALLED[/green]", f"Version: {version} | Command: {cmd}")
        else:
            err = opencode_status.get("health", {}).get("error", "Unknown error")
            attempts = opencode_status.get("attempts", [])
            details = str(err)
            if attempts:
                tried = ", ".join(str(item.get("command")) for item in attempts)
                details += f" | Tried: {tried}"
            table.add_row("OpenCode", "[red]NOT INSTALLED[/red]", details)

        INSTALL_CONSOLE.print(Panel(table, title="FocusTracer Install Center", border_style="blue"))
        return

    print("\n" + "=" * 70)
    print("  FocusTracer - Agent Installation & Management")
    print("=" * 70)
    
    print("\n  Current Installation Status:\n")
    
    # Ollama status
    if ollama_status["installed"]:
        print("  [OK] Ollama:    INSTALLED")
        models = ollama_status.get("models", [])
        if models:
            print(f"    Available models: {', '.join(models[:5])}")
            if len(models) > 5:
                print(f"                      ... and {len(models) - 5} more")
    else:
        print("  [--] Ollama:    NOT INSTALLED")
        error = ollama_status.get("health", {}).get("error", "Unknown error")
        if "Connection refused" in error or "ConnectionError" in error:
            print("    Hint: Ollama service not running or not accessible")
    
    # OpenCode status
    if opencode_status["installed"]:
        version = opencode_status.get("version", "unknown")
        print("  [OK] OpenCode:  INSTALLED")
        if version:
            print(f"    Version: {version}")
        detected_cmd = opencode_status.get("detected_command")
        if detected_cmd:
            print(f"    Command: {detected_cmd}")
    else:
        print("  [--] OpenCode:  NOT INSTALLED")
        error = opencode_status.get("health", {}).get("error", "Unknown error")
        if error:
            print(f"    Error: {error}")
        attempts = opencode_status.get("attempts", [])
        if attempts:
            tried = ", ".join(str(item.get("command")) for item in attempts)
            print(f"    Tried: {tried}")


def _print_menu() -> None:
    """Kurulum menüsünü göster."""
    if HAS_RICH and INSTALL_CONSOLE is not None and Panel is not None:
        menu_text = (
            "[bold]1.[/bold] Install/configure Ollama\n"
            "[bold]2.[/bold] Install OpenCode\n"
            "[bold]3.[/bold] Download Ollama model\n"
            "[bold]4.[/bold] Refresh status\n"
            "[bold]5.[/bold] Run agent health check (both)\n"
            "[bold]0.[/bold] Exit"
        )
        INSTALL_CONSOLE.print(Panel(menu_text, title="Options", border_style="magenta"))
        return

    print("\n" + "-" * 70)
    print("  Options:\n")
    print("    1. Install/configure Ollama")
    print("    2. Install OpenCode")
    print("    3. Download Ollama model")
    print("    4. Refresh status")
    print("    5. Run agent health check (both)")
    print("    0. Exit\n")
    print("-" * 70)


def _install_ollama_interactive() -> int:
    """Ollama kurulum talimatlarını göster."""
    print("\n" + "=" * 70)
    print("  ▸ Ollama Installation Guide")
    print("=" * 70)
    
    print("\n  Ollama is a tool to run LLMs locally.\n")
    print("  Installation Instructions:\n")
    print("    1. Visit: https://ollama.ai")
    print("    2. Download the installer for your platform")
    print("    3. Run the installer and follow the setup wizard")
    print("    4. After installation, Ollama runs on: http://localhost:11434")
    print("    5. Run this script again to download models\n")
    
    print("  After Ollama is installed, you can download models with:")
    print("    → Option 3 in this menu\n")
    
    input("  Press Enter to continue...")
    return 0


def _install_opencode_interactive(opencode_cmd: str = "opencode") -> int:
    """OpenCode kurulum ve troubleshooting."""
    while True:
        print("\n" + "=" * 70)
        print("  ▸ OpenCode Installation & Troubleshooting")
        print("=" * 70)
        
        # Mevcut durumu kontrol et
        opencode_status = _check_opencode_status(opencode_cmd=opencode_cmd)
        
        if opencode_status["installed"]:
            version = opencode_status.get("version", "unknown")
            print(f"\n  ✓ OpenCode is already INSTALLED")
            print(f"    Version: {version}")
            input("\n  Press Enter to continue...")
            return 0
        
        print("\n  OpenCode is a Node.js CLI-based AI coding agent.")
        print("  It helps with debugging and code fixing.\n")
        print("  Options:\n")
        print("    1. Automatically install OpenCode via npm")
        print("    2. Test OpenCode command (troubleshooting)")
        print("    3. Show manual installation instructions")
        print("    0. Back to main menu\n")
        
        choice = _install_ask("Enter your choice (0-3)", default="0").strip()
        
        if choice == "1":
            _auto_install_opencode(opencode_cmd=opencode_cmd)
        elif choice == "2":
            _test_opencode_command(opencode_cmd=opencode_cmd)
        elif choice == "3":
            _show_opencode_manual()
        elif choice == "0":
            return 0
        else:
            print("\n  ✗ Invalid choice.")
            input("  Press Enter to continue...")


def _auto_install_opencode(opencode_cmd: str = "opencode") -> None:
    """OpenCode'u npm ile otomatik kur."""
    print("\n" + "=" * 70)
    print("  ▸ Installing OpenCode via npm...")
    print("=" * 70 + "\n")
    
    # First check if npm is installed
    print("  Checking npm installation...\n")
    try:
        npm_check = subprocess.run(
            ["npm", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if npm_check.returncode != 0:
            print("  ✗ ERROR: npm is not installed!\n")
            print("  Solutions:")
            print("    1. Install Node.js from https://nodejs.org/")
            print("    2. This will include npm package manager")
            print("    3. Restart your terminal after installation\n")
            input("  Press Enter to continue...")
            return
        npm_version = npm_check.stdout.strip()
        print(f"  ✓ npm found: {npm_version}\n")
    except FileNotFoundError:
        print("  ✗ ERROR: 'npm' command not found in PATH!\n")
        print("  Solutions:")
        print("    1. Install Node.js from https://nodejs.org/")
        print("    2. Restart your terminal after installation\n")
        input("  Press Enter to continue...")
        return
    except Exception as e:
        print(f"  ✗ Error checking npm: {str(e)}\n")
        input("  Press Enter to continue...")
        return
    
    # Install OpenCode globally
    try:
        print("  → Running: npm i -g opencode-ai\n")
        result = subprocess.run(
            ["npm", "i", "-g", "opencode-ai"],
            capture_output=False,
            text=True,
            timeout=300  # 5 dakika timeout
        )
        
        print("\n" + "=" * 70)
        if result.returncode == 0:
            print("  ✓ Installation completed successfully!")
            
            # Kurulumun başarılı olup olmadığını kontrol et
            print("  → Verifying installation...\n")
            verify_status = _check_opencode_status(opencode_cmd=opencode_cmd)

            if verify_status.get("installed"):
                version = verify_status.get("version") or "unknown"
                detected_cmd = verify_status.get("detected_command") or opencode_cmd
                print(f"  ✓ Verified: OpenCode {version}")
                print(f"    Command: {detected_cmd}\n")
            else:
                print("  ⚠ Installation completed but verification failed.")
                print("    Try restarting your terminal or checking PATH.\n")
        else:
            print("  ✗ Installation failed!")
            print("    Please check your npm installation and try again.\n")
        
        input("  Press Enter to continue...")
    except subprocess.TimeoutExpired:
        print("\n  ✗ Installation timeout. Please try again.")
        input("  Press Enter to continue...")
    except Exception as e:
        print(f"\n  ✗ Error: {str(e)}")
        input("  Press Enter to continue...")


def _test_opencode_command(opencode_cmd: str = "opencode") -> None:
    """OpenCode komutunu test et ve troubleshoot."""
    print("\n" + "=" * 70)
    print("  ▸ OpenCode Command Troubleshooting")
    print("=" * 70 + "\n")
    
    print(f"  Testing preferred command: {opencode_cmd} --version\n")

    status = _check_opencode_status(opencode_cmd=opencode_cmd)
    if status.get("installed"):
        print(f"  [OK] SUCCESS: {status.get('version') or 'unknown version'}")
        print(f"  [OK] Detected command: {status.get('detected_command')}\n")
    else:
        print("  [--] OpenCode command could not be verified.\n")
        print("  Attempt log:")
        for attempt in status.get("attempts", []):
            print(f"    - {attempt.get('command')}: {attempt.get('error') or 'not available'}")
        print("\n  Solutions:")
        print("    1. Ensure OpenCode is installed: npm i -g opencode-ai")
        print("    2. Restart your terminal (PowerShell/CMD)")
        print("    3. Or use --opencode-cmd \"python -m opencode\"\n")
    
    input("  Press Enter to continue...")


def _show_opencode_manual() -> None:
    """OpenCode manual kurulum talimatlarını göster."""
    print("\n" + "=" * 70)
    print("  ▸ OpenCode Manual Installation")
    print("=" * 70)
    
    print("\n  ℹ OpenCode is a Node.js CLI-based AI agent.\n")
    
    print("  Prerequisites: Node.js and npm\n")
    print("    → Download from: https://nodejs.org/\n")
    
    print("  Option 1: Install via npm (Recommended)\n")
    print("    npm i -g opencode-ai")
    print("    opencode --version\n")
    
    print("  Option 2: Verify installation\n")
    print("    # Check if installed correctly:")
    print("    opencode --version")
    print("    ")
    print("    # List global npm packages:")
    print("    npm list -g opencode-ai\n")
    
    print("  Option 3: If npm command not found\n")
    print("    1. Ensure Node.js is installed: node --version")
    print("    2. Check npm: npm --version")
    print("    3. Restart your terminal")
    print("    4. Try again\n")
    
    print("  Documentation:")
    print("    https://github.com/starlang-ai/opencode\n")
    
    input("  Press Enter to continue...")



def _download_ollama_model_interactive(
    ollama_url: str = "http://localhost:11434",
    model: str = DEFAULT_MODEL,
) -> int:
    """Ollama model indirme menüsü."""
    print("\n" + "=" * 70)
    print("  ▸ Download Ollama Model")
    print("=" * 70)
    
    # Mevcut modelleri kontrol et
    ollama_status = _check_ollama_status(ollama_url=ollama_url, model=model)
    
    if not ollama_status["installed"]:
        print("\n  ✗ ERROR: Ollama is not installed or not running.")
        print("    → Please install Ollama first (Option 1)")
        input("\n  Press Enter to continue...")
        return 1
    
    existing_models = ollama_status.get("models", [])
    print(f"\n  Currently available models ({len(existing_models)}):\n")
    for i, model in enumerate(existing_models, 1):
        print(f"    {i}. {model}")
    
    print("\n  Available models to download:\n")
    models_to_download = [
        ("qwen2.5:3b", "Small and fast model (3.2GB)"),
        ("qwen2.5-coder:7b", "Code-specialized model (4.6GB)"),
    ]
    
    for i, (model, desc) in enumerate(models_to_download, 1):
        status = "✓" if model in existing_models else "○"
        print(f"    {status} {i}. {model}")
        print(f"       {desc}\n")
    
    print("    0. Back to menu\n")
    
    choice = _install_ask("Enter your choice (0-2)", default="0").strip()
    
    if choice == "1":
        model_name = "qwen2.5:3b"
    elif choice == "2":
        model_name = "qwen2.5-coder:7b"
    elif choice == "0":
        return 0
    else:
        print("\n  ✗ Invalid choice.")
        input("  Press Enter to continue...")
        return 1
    
    # Modeli zaten indirilmiş mi kontrol et
    if model_name in existing_models:
        print(f"\n  ℹ Model '{model_name}' is already installed.")
        input("  Press Enter to continue...")
        return 0
    
    # Model indirme başlat
    print(f"\n  ↓ Downloading model: {model_name}")
    print("    This may take a few minutes...\n")
    
    try:
        result = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=False,
            text=True,
            timeout=600  # 10 dakika timeout
        )
        
        if result.returncode == 0:
            print(f"\n  ✓ Model '{model_name}' downloaded successfully!")
            input("  Press Enter to continue...")
            return 0
        else:
            print(f"\n  ✗ Failed to download model '{model_name}'.")
            input("  Press Enter to continue...")
            return 1
    except FileNotFoundError:
        print("\n  ✗ ERROR: 'ollama' command not found in PATH.")
        print("    → Ensure Ollama is installed and added to your system PATH.")
        input("  Press Enter to continue...")
        return 1
    except subprocess.TimeoutExpired:
        print("\n  ✗ ERROR: Download timeout. Please try again or check your connection.")
        input("  Press Enter to continue...")
        return 1
    except Exception as e:
        print(f"\n  ✗ ERROR: {str(e)}")
        input("  Press Enter to continue...")
        return 1


def install_agent(args: argparse.Namespace) -> int:
    """Interactive menu for installing and managing agents."""
    if args.status:
        ollama_status = _check_ollama_status(ollama_url=args.ollama_url, model=args.model)
        opencode_status = _check_opencode_status(opencode_cmd=args.opencode_cmd, model=args.model)
        _print_status_panel(ollama_status, opencode_status)
        return 0

    if args.agent == "ollama":
        _install_ollama_interactive()
        return 0

    if args.agent == "opencode":
        return _install_opencode_interactive(opencode_cmd=args.opencode_cmd)

    while True:
        # Mevcut durumu kontrol et
        ollama_status = _check_ollama_status(ollama_url=args.ollama_url, model=args.model)
        opencode_status = _check_opencode_status(opencode_cmd=args.opencode_cmd, model=args.model)
        
        # Paneli göster
        _print_status_panel(ollama_status, opencode_status)
        _print_menu()

        choice = _install_ask("Enter your choice (0-5)", default="0").strip()
        
        if choice == "1":
            _install_ollama_interactive()
        elif choice == "2":
            _install_opencode_interactive(opencode_cmd=args.opencode_cmd)
        elif choice == "3":
            if _download_ollama_model_interactive(ollama_url=args.ollama_url, model=args.model) != 0:
                pass  # Hata mesajı zaten gösterildi
        elif choice == "4":
            # Refresh için loop devam et
            continue
        elif choice == "5":
            # Health check çalıştır (both)
            print("\n  Ollama health:\n")
            check_agent(
                argparse.Namespace(
                    agent="ollama",
                    model=args.model,
                    ollama_url=args.ollama_url,
                    opencode_cmd=args.opencode_cmd,
                )
            )
            print("\n  OpenCode health:\n")
            check_agent(
                argparse.Namespace(
                    agent="opencode",
                    model=args.model,
                    ollama_url=args.ollama_url,
                    opencode_cmd=args.opencode_cmd,
                )
            )
            input("\n  Press Enter to continue...")
        elif choice == "0":
            print("\n  Goodbye!")
            return 0
        else:
            print("\n  ✗ Invalid choice. Please try again.")
            input("  Press Enter to continue...")


def _manual_manifest(args: argparse.Namespace) -> TargetManifest:
    return TargetManifest.from_cli(
        functions=args.function,
        files=args.file,
        lines=args.line,
        thread_names=args.thread_name,
    )


def _inventory_for_args(args: argparse.Namespace):
    target_script = Path(args.target_script).resolve()
    project_root = (
        Path(args.project_root).resolve() if args.project_root else target_script.parent
    )
    return build_code_inventory(project_root=project_root, target_script=target_script)


def _resolve_output_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    output = getattr(args, "output", None)
    if output is None:
        output = getattr(args, "trace_output", None)

    if output:
        trace_path = Path(output).resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_stem = Path(args.target_script).stem
        output_dir = getattr(args, "output_dir", None)
        if output_dir is None:
            output_dir = getattr(args, "trace_output_dir", "output")
        trace_path = Path(output_dir).resolve() / f"{timestamp}_{script_stem}.xml"
    manifest_path = trace_path.with_suffix(".targets.json")
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    return trace_path, manifest_path


def _resolve_suggest_manifest_output(args: argparse.Namespace) -> Path | None:
    if args.manifest_output:
        manifest_path = Path(args.manifest_output).resolve()
    elif args.save_manifest:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_stem = Path(args.target_script).stem
        manifest_path = (
            Path(args.output_dir).resolve() / f"{timestamp}_{script_stem}.targets.json"
        )
    else:
        return None

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    return manifest_path


def _runtime_manifest_for_script(
    manifest: TargetManifest, target_script: str | Path
) -> TargetManifest:
    script_stem = Path(target_script).stem
    runtime_functions: list[str] = []
    for function_name in manifest.functions:
        runtime_functions.append(function_name)
        parts = function_name.split(".")
        if parts:
            runtime_functions.append(parts[-1])
        if len(parts) >= 2:
            runtime_functions.append(".".join(parts[-2:]))

        suffix = None
        if function_name.startswith(f"{script_stem}."):
            suffix = function_name[len(script_stem) + 1 :]
        else:
            marker = f".{script_stem}."
            if marker in function_name:
                suffix = function_name.split(marker, 1)[1]
        if suffix:
            runtime_functions.append(f"__main__.{suffix}")
            runtime_functions.append(suffix)

    return TargetManifest(
        functions=runtime_functions,
        files=list(manifest.files),
        lines=list(manifest.lines),
        thread_names=list(manifest.thread_names),
    ).normalized()


def check_agent(args: argparse.Namespace) -> int:
    agent = _build_agent(args.agent, args.model, args.ollama_url, args.opencode_cmd)
    health = agent.health()
    print(json.dumps(health, indent=2))
    if not health.get("ok"):
        return 1
    return 0 if health.get("model_available") else 2


def _execute_trace_with_manifest(
    args: argparse.Namespace, merged_manifest: TargetManifest
) -> int:
    if not merged_manifest.has_targets():
        print(
            "Error: at least one target is required. Use --function or --auto-targets."
        )
        return 1
    if merged_manifest.requires_function_targets():
        print(
            "Error: function targets are required in phase 1. File/line-only activation is not supported yet."
        )
        return 1

    runtime_manifest = _runtime_manifest_for_script(merged_manifest, args.target_script)
    trace_path, manifest_path = _resolve_output_paths(args)
    manifest_path.write_text(merged_manifest.to_json() + "\n", encoding="utf-8")

    recorder = TraceRecorder(
        output_file=str(trace_path),
        output_format="xml",
        detail_level=args.detail,
        max_depth=args.max_depth,
        max_iterations=args.max_iterations,
        schema_version=args.schema_version,
        enable_threading=True,
        manifest=runtime_manifest,
    )

    patcher = DynamicPatcher(
        tracer=recorder, target_functions=merged_manifest.functions
    )
    patch_results = patcher.patch_all()
    attempted_patches = {target: ok for target, ok in patch_results.items() if ok}
    if attempted_patches:
        print(f"[*] Patched importable targets: {sorted(attempted_patches)}")

    with TraceContext(recorder=recorder):
        runpy.run_path(str(Path(args.target_script).resolve()), run_name="__main__")

    patcher.unpatch_all()

    if not args.skip_validate:
        from focustracer.validate.validator import validate_xml_against_xsd

        is_valid, errors = validate_xml_against_xsd(str(trace_path))
        print(f"[*] XML validation: {'ok' if is_valid else 'failed'}")
        if not is_valid:
            print("[!] Validation errors:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

    print(f"[*] Trace written to {trace_path}")
    print(f"[*] Target manifest written to {manifest_path}")
    return 0


def suggest_targets(args: argparse.Namespace) -> int:
    agent = _build_agent(args.agent, args.model, args.ollama_url, args.opencode_cmd)
    health = agent.health()
    if not health.get("ok"):
        print(json.dumps(health, indent=2))
        print("AI agent is not healthy. Cannot suggest targets.")
        return 1
    if not health.get("model_available"):
        print(json.dumps(health, indent=2))
        print("Configured model is not available for the selected agent.")
        return 2

    inventory = _inventory_for_args(args)
    manual_manifest = _manual_manifest(args)
    suggested = TargetManifest.from_dict(
        agent.suggest_targets(
            inventory.to_prompt_payload(),
            manual_targets=manual_manifest.to_dict(),
            error_context=args.error_context,
            user_hint=args.hint,
        )
    )
    merged = manual_manifest.merge(suggested)
    print(merged.to_json())

    manifest_path = _resolve_suggest_manifest_output(args)
    if manifest_path:
        manifest_path.write_text(merged.to_json() + "\n", encoding="utf-8")
        print(f"[*] Suggested manifest written to {manifest_path}", file=sys.stderr)

    if args.execute:
        print("[*] Executing trace with suggested targets...", file=sys.stderr)
        return _execute_trace_with_manifest(args, merged)

    return 0


def run_trace(args: argparse.Namespace) -> int:
    manual_manifest = _manual_manifest(args)
    inventory = _inventory_for_args(args)
    agent: BaseAIAgent | None = None
    ai_manifest = TargetManifest()

    if args.auto_targets:
        agent = _build_agent(args.agent, args.model, args.ollama_url, args.opencode_cmd)
        health = agent.health()
        if not health.get("ok"):
            print(json.dumps(health, indent=2))
            return 1
        if not health.get("model_available"):
            print(json.dumps(health, indent=2))
            return 2
        ai_manifest = TargetManifest.from_dict(
            agent.suggest_targets(
                inventory.to_prompt_payload(),
                manual_targets=manual_manifest.to_dict(),
                error_context=args.error_context,
                user_hint=args.hint,
            )
        )

    merged_manifest = manual_manifest.merge(ai_manifest)

    # No function targets and no LLM selection → trace every function defined in
    # the target script. Removes the "must name a function" friction; the recorder
    # already supports untargeted tracing, this just scopes it to the user's script.
    if not merged_manifest.functions and not args.auto_targets:
        all_functions = list(inventory.functions)
        if all_functions:
            print(
                f"[*] No function targets given — tracing all {len(all_functions)} "
                f"function(s) defined in {Path(args.target_script).name}. "
                f"Use --function to focus.",
                file=sys.stderr,
            )
            merged_manifest = merged_manifest.merge(
                TargetManifest(functions=all_functions)
            )

    return _execute_trace_with_manifest(args, merged_manifest)


def load_trace(args: argparse.Namespace) -> int:
    """Load a saved XML trace and display it in the terminal."""
    from focustracer.core.loader import TraceLoader
    from focustracer.core.display import TraceDisplayer

    trace_file = args.trace_file

    # Optional XSD validation before display
    if not args.no_validate:
        from focustracer.validate.validator import validate_xml_against_xsd
        is_valid, errors = validate_xml_against_xsd(trace_file)
        if not is_valid:
            print(f"[!] XSD validation failed for: {trace_file}", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            print("[!] Use --no-validate to skip validation and display anyway.", file=sys.stderr)
            return 1

    try:
        doc = TraceLoader().load(trace_file)
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[!] Failed to parse trace: {exc}", file=sys.stderr)
        return 1

    displayer = TraceDisplayer()
    displayer.display(
        doc,
        summary_only=args.summary,
        filter_function=args.filter_function,
        filter_thread=args.filter_thread,
    )
    return 0


def _print_slice_failure(exc: Exception, args: argparse.Namespace) -> None:
    """Print a slice/explain failure with an actionable hint."""
    msg = str(exc)
    print(f"[!] Slice failed: {msg}", file=sys.stderr)
    if "no exception" in msg.lower() and not args.at:
        print(
            "    This trace has no exception, and --at-exception is the default.\n"
            "    Slice a specific value instead:  --at LINE[:VAR]   (e.g. --at 42:total)",
            file=sys.stderr,
        )


def slice_trace_cmd(args: argparse.Namespace) -> int:
    """Compute a backward dynamic slice and embed it into a copy of the trace."""
    from focustracer.core.slicer import slice_trace, annotate_trace_with_slice, slice_result_to_dicts

    trace_file = args.trace_file
    at_exception = args.at_exception or not args.at

    try:
        model, result = slice_trace(
            trace_file,
            at_exception=at_exception,
            at=args.at,
            include_control=not args.no_control,
        )
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        _print_slice_failure(exc, args)
        return 1

    if not any(step.event_id is not None and (step.uses or step.defs) for step in model.steps):
        print(
            "[!] This trace has no reads — slicing needs a detailed schema>=2.3 trace.\n"
            "    Re-run: focustracer run --detail detailed --schema-version 2.3 ...",
            file=sys.stderr,
        )
        return 1

    out_path = annotate_trace_with_slice(trace_file, model, result, args.output)

    if not args.no_validate:
        from focustracer.validate.validator import validate_xml_against_xsd
        is_valid, errors = validate_xml_against_xsd(out_path)
        if not is_valid:
            print(f"[!] Sliced XML failed XSD validation: {out_path}", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

    nodes = slice_result_to_dicts(model, result)
    print(f"[*] Criterion: {result.criterion_label}")
    print(f"[*] Slice: {len(nodes)} statement(s)"
          f"  (control {'on' if result.include_control else 'off'})")
    print("-" * 60)
    for d in nodes:
        marker = {"criterion": "◆", "control": "▸", "data": "·"}.get(d["dependency"], " ")
        fn = d["function"] or "?"
        print(f"  {marker} L{d['line']:<4} {fn:<14} {d['source']}")
    print("-" * 60)
    print(f"[*] Sliced trace written to {out_path}")
    print("[*] XML validation: ok" if not args.no_validate else "")
    return 0


def explain_cmd(args: argparse.Namespace) -> int:
    """Compute a slice, then ask the LLM for a root-cause explanation."""
    from focustracer.core.slicer import slice_trace
    from focustracer.core.explain import build_slice_context, explain_slice

    at_exception = args.at_exception or not args.at
    try:
        model, result = slice_trace(
            args.trace_file, at_exception=at_exception, at=args.at,
            include_control=not args.no_control,
        )
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        _print_slice_failure(exc, args)
        return 1

    context = build_slice_context(model, result)
    if args.show_context:
        print("=== SLICE CONTEXT (sent to model) ===")
        print(context)
        print("=" * 40)

    agent = _build_agent(args.agent, args.model, args.ollama_url, args.opencode_cmd)
    health = agent.health()
    if not health.get("ok"):
        print(json.dumps(health, indent=2))
        print("[!] AI agent is not reachable — cannot explain. "
              "The slice above/`focustracer slice` still works offline.", file=sys.stderr)
        return 1

    try:
        explanation, _ = explain_slice(
            agent, model, result, error_context=args.error_context
        )
    except Exception as exc:  # noqa: BLE001 — surface any agent error to the user
        print(f"[!] Explanation failed: {exc}", file=sys.stderr)
        return 1

    print(f"[*] Criterion: {result.criterion_label}")
    print("-" * 60)
    print(explanation.strip())
    print("-" * 60)

    if args.output:
        Path(args.output).write_text(explanation.strip() + "\n", encoding="utf-8")
        print(f"[*] Explanation written to {args.output}", file=sys.stderr)
    return 0


def _fmt_state(state: dict, limit: int = 12) -> str:
    items = [f"{n}={v[0]}" for n, v in list(state.items())[:limit]]
    if len(state) > limit:
        items.append(f"… (+{len(state) - limit})")
    return ", ".join(items) if items else "(empty)"


def reverse_cmd(args: argparse.Namespace) -> int:
    """Reconstruct observable state at a point and rewind step-by-step."""
    from focustracer.core.reverse import reverse_trace, result_to_dict, state_diff

    try:
        result = reverse_trace(
            args.trace_file,
            at_exception=args.at_exception,
            at_event=args.at_event,
            at_line=args.at_line,
            function=args.function,
            step_back=max(0, args.step_back),
        )
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[!] Reverse failed: {exc}", file=sys.stderr)
        return 1

    t = result.target
    print(f"[*] Reverse state @ {result.label}  —  {t.function} L{t.line}: {t.source}")
    print("-" * 60)
    for name, (value, vtype) in t.state.items():
        print(f"    {name} = {value}    ({vtype})")
    print("-" * 60)

    if result.timeline:
        print(f"◀ Reverse timeline — {len(result.timeline)} step(s) back:")
        ordered = result.timeline + [t]
        # walk backward from the moment just before the target
        for i in range(len(ordered) - 2, -1, -1):
            m = ordered[i]
            step = i - (len(ordered) - 1)
            print(f"  {step:>3}  {m.function} L{m.line}: {m.source}")
            later = ordered[i + 1]
            if later.frame_id == m.frame_id:
                diffs = state_diff(m, later)
                for name, ev, lv in diffs:
                    print(f"         undo  {name}: {lv} → {ev}")
            else:
                print(f"         ↑ returned from {later.function} to {m.function}")
                print(f"         state: {_fmt_state(m.state)}")
        print("-" * 60)

    if args.json:
        Path(args.json).write_text(
            json.dumps(result_to_dict(result), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[*] Reconstructed state written to {args.json}", file=sys.stderr)
    return 0


def replay_cmd(args: argparse.Namespace) -> int:
    """Navigate a trace with a movable cursor: forward, backward, jump, inspect."""
    from focustracer.core.replay import ReplaySession

    try:
        session = ReplaySession.from_trace(args.trace_file)
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[!] Replay failed: {exc}", file=sys.stderr)
        return 1

    # -- position the cursor at the requested start point ------------------
    try:
        if args.seq is not None:
            session.jump_to_seq(args.seq)
        elif args.at_event is not None:
            session.jump_to_event(args.at_event)
        elif args.at_line is not None:
            session.jump_to_line(args.at_line, args.function)
        elif args.at_exception:
            session.jump_to_exception()
        # else: default cursor stays at seq 0 (start of execution)
    except ValueError as exc:
        print(f"[!] Replay failed: {exc}", file=sys.stderr)
        return 1

    if args.step > 0:
        session.step_forward(args.step)
    elif args.step < 0:
        session.step_back(-args.step)

    # Debugger-style stepping (frame-depth aware), applied from the start point.
    if args.into:
        session.step_into(back=args.back)
    elif args.over:
        session.step_over(back=args.back)
    elif args.out:
        session.step_out(back=args.back)

    if args.list:
        print(f"[*] Timeline — {session.total} line-event(s), cursor at #{session.cursor}")
        print("-" * 60)
        for m in session.moments:
            mark = "▶" if m.seq == session.cursor else " "
            print(f"  {mark} #{m.seq:<4} {m.function} L{m.line}: {m.source}")
        print("-" * 60)
        return 0

    cur = session.current
    arrows = []
    if session.can_back:
        arrows.append("◀ back")
    if session.can_forward:
        arrows.append("forward ▶")
    print(f"[*] Replay cursor #{session.cursor}/{session.total - 1}  "
          f"({' · '.join(arrows) or 'single moment'})")
    print(f"    @ {cur.function} L{cur.line}: {cur.source}")
    print("-" * 60)
    for name, (value, vtype) in cur.state.items():
        print(f"    {name} = {value}    ({vtype})")
    print("-" * 60)

    if args.window > 0:
        view = session.to_dict(window=args.window)
        print("Timeline around cursor:")
        for entry in view["timeline"]:
            mark = "▶" if entry["is_cursor"] else " "
            print(f"  {mark} #{entry['seq']:<4} {entry['function']} L{entry['line']}: {entry['source']}")
            for u in entry.get("change", []):
                print(f"        Δ {u['name']}: {u['from']} → {u['to']}")
        print("-" * 60)

    if args.def_var:
        site = session.def_of(args.def_var)
        if site is None:
            print(f"[!] '{args.def_var}' is not defined at the cursor.")
        else:
            m = site.moment
            origin = "(call boundary)" if site.old_value is None else f"{site.old_value} → {site.new_value}"
            print(f"[*] '{args.def_var}' last defined at #{m.seq}  {m.function} L{m.line}: {m.source}")
            print(f"    {origin}")
        print("-" * 60)

    if args.json:
        Path(args.json).write_text(
            json.dumps(session.to_dict(window=args.window), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[*] Cursor view written to {args.json}", file=sys.stderr)
    return 0


def _align_nav_requested(args: argparse.Namespace) -> bool:
    """True when the user asked for side-by-side cursor navigation."""
    return (
        args.seq is not None
        or args.at_event is not None
        or args.at_line is not None
        or args.at_exception
        or bool(args.step)
        or args.into
        or args.over
        or args.out
    )


def _align_set_cmd(args: argparse.Namespace) -> int:
    """3+ traces: curate them as a set (distance matrix, reference, outlier)."""
    from focustracer.core.align import TraceSet

    try:
        summary = TraceSet(args.traces).summary()
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[!] Align failed: {exc}", file=sys.stderr)
        return 1

    n = len(summary.paths)
    print(f"[*] Trace set — {n} traces of the same program")
    for i, (path, length) in enumerate(zip(summary.paths, summary.lengths)):
        print(f"    #{i}  {length:>6} statements   {Path(path).name}")
    print("-" * 60)
    print("[*] Pairwise normalized distance (0 = identical):")
    print("        " + "".join(f"   #{j:<4}" for j in range(n)))
    for i, row in enumerate(summary.matrix):
        print(f"    #{i:<3}" + "".join(f"  {v:>6.3f}" for v in row))
    print("-" * 60)
    ref, out = summary.reference, summary.outlier
    print(f"[*] Reference (medoid): #{ref}  {Path(summary.paths[ref]).name}"
          "   ← most representative run")
    print(f"[*] Outlier:            #{out}  {Path(summary.paths[out]).name}"
          f"   ← furthest from the reference ({summary.matrix[ref][out]:.3f})")
    print(f"[*] Mean pairwise distance: {summary.mean_distance:.3f}")
    print("-" * 60)

    if args.json:
        Path(args.json).write_text(
            json.dumps(summary.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[*] Trace-set summary written to {args.json}", file=sys.stderr)
    return 0


def _align_nav_cmd(args: argparse.Namespace, trace_a: str, trace_b: str) -> int:
    """Two traces, side by side: one cursor on A, the aligned point in B."""
    from focustracer.core.align import AlignedPair

    try:
        pair = AlignedPair(trace_a, trace_b)
        pair.seek(
            seq=args.seq, event=args.at_event, line=args.at_line,
            function=args.function, at_exception=args.at_exception,
        )
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[!] Align failed: {exc}", file=sys.stderr)
        return 1

    if args.step > 0:
        pair.step_forward(args.step)
    elif args.step < 0:
        pair.step_back(-args.step)
    if args.into:
        pair.step("into", back=args.back)
    elif args.over:
        pair.step("over", back=args.back)
    elif args.out:
        pair.step("out", back=args.back)

    al = pair.alignment
    print(f"[*] A: {Path(trace_a).name}   B: {Path(trace_b).name}")
    print(f"[*] Distance: {al.distance}  (normalized {al.normalized_distance:.3f})   "
          f"matched {al.matched} · gaps {al.gaps}")
    print("-" * 60)
    am = pair.a.current
    print(f"    A #{pair.a.cursor}/{pair.a.total - 1}  {am.function} L{am.line}: {am.source}")
    bm = pair.aligned_moment()
    if bm is None:
        print("    B  —      diverged: no statement in B aligns with A's cursor")
    else:
        print(f"    B #{bm.seq}/{pair.b.total - 1}  {bm.function} L{bm.line}: {bm.source}")
    print("-" * 60)

    if bm is not None:
        delta = pair.state_delta()
        if not delta:
            print("    (states agree at this point)")
        else:
            print("    Variable deltas at the aligned point:")
            for d in delta:
                print(f"      {d['name']:<16} A = {str(d['a']):<20} B = {d['b']}")
        print("-" * 60)

    if args.window > 0:
        view = pair.to_dict(window=args.window)
        for side in ("a", "b"):
            sub = view[side]
            if sub is None:
                continue
            print(f"Timeline around {side.upper()}'s cursor:")
            for entry in sub["timeline"]:
                mark = "▶" if entry["is_cursor"] else " "
                print(f"  {mark} #{entry['seq']:<4} {entry['function']} "
                      f"L{entry['line']}: {entry['source']}")
        print("-" * 60)

    if args.json:
        Path(args.json).write_text(
            json.dumps(pair.to_dict(window=args.window), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[*] Aligned cursor view written to {args.json}", file=sys.stderr)
    return 0


def align_cmd(args: argparse.Namespace) -> int:
    """Align traces of the same program and report their distance.

    Three modes, all FR-KIO2-03:
      * 2 traces               → distance + alignment encoding (the Output);
      * 2 traces + navigation  → one session over both at once (the Objective);
      * 3+ traces              → trace-set curation (the Input).
    """
    from focustracer.core.align import align_traces

    if len(args.traces) < 2:
        print("[!] align needs at least two traces.", file=sys.stderr)
        return 1
    if len(args.traces) > 2:
        if _align_nav_requested(args):
            print("[!] Side-by-side navigation works on exactly two traces.", file=sys.stderr)
            return 1
        return _align_set_cmd(args)

    trace_a, trace_b = args.traces
    if _align_nav_requested(args):
        return _align_nav_cmd(args, trace_a, trace_b)

    try:
        al = align_traces(trace_a, trace_b)
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[!] Align failed: {exc}", file=sys.stderr)
        return 1

    print(f"[*] Trace A: {al.len_a} statements   Trace B: {al.len_b} statements")
    print(f"[*] Distance: {al.distance}  (normalized {al.normalized_distance:.3f})")
    print(f"[*] Matched: {al.matched}   Gaps (divergences): {al.gaps}")
    if al.distance == 0:
        print("[*] Traces are identical.")
    print("-" * 60)

    if args.show_alignment:
        a_tok = _align_tokens(trace_a)
        b_tok = _align_tokens(trace_b)
        for ai, bj in al.pairs:
            if ai is not None and bj is not None:
                mark = "=" if a_tok[ai] == b_tok[bj] else "≠"
                print(f"  {mark} {a_tok[ai]:<24} {b_tok[bj]}")
            elif ai is not None:
                print(f"  − {a_tok[ai]:<24} (only in A)")
            else:
                print(f"  + {'':<24} {b_tok[bj]}  (only in B)")
        print("-" * 60)

    if args.divergences:
        divs = al.divergences()
        if not divs:
            print("[*] No divergences — the traces align 1:1.")
        for d in divs:
            where = "A" if d.side == "a" else "B"
            other = "B" if d.side == "a" else "A"
            anchor = f"after {other} #{d.at}" if d.at is not None else "at the start"
            print(f"  {where} #{d.start}..{d.end - 1}  "
                  f"({d.length} statement(s) only in {where}, {anchor})")
        print("-" * 60)

    if args.json:
        payload = al.to_dict()
        payload["divergences"] = [d.to_dict() for d in al.divergences()]
        Path(args.json).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"[*] Alignment written to {args.json}", file=sys.stderr)
    return 0


def _align_tokens(path: str) -> list[str]:
    from focustracer.core.align import trace_tokens
    return trace_tokens(path)


def launch_gui(args: argparse.Namespace) -> int:
    """Start the FocusTracer web UI (FastAPI + Uvicorn)."""
    import webbrowser
    import uvicorn  # type: ignore[import]

    host = args.host
    port = args.port
    url = f"http://{host}:{port}"

    if not args.no_browser:
        # Open browser after a short delay so the server has time to start
        def _open():
            import time
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    print(f"[FocusTracer GUI] Starting server at {url}")
    print("[FocusTracer GUI] Press Ctrl+C to stop.")

    uvicorn.run(
        "focustracer.gui.server:app",
        host=host,
        port=port,
        log_level="warning",
    )
    return 0


def _force_utf8_output() -> None:
    """Make the CLI's box-drawing / arrow output survive a legacy console codepage.

    The trace views use ``▶``, ``Δ``, ``≠`` and friends. On Windows the console
    still defaults to a regional codepage (cp1254 on a Turkish install), which
    raises ``UnicodeEncodeError`` mid-render. Re-encoding as UTF-8 with a
    replacement fallback keeps the output readable instead of crashing.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass  # already UTF-8, or a stream that cannot be reconfigured


def main(argv: Optional[list[str]] = None) -> int:
    _force_utf8_output()
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0
    if args.command == "gui":
        return launch_gui(args)
    if args.command == "check-agent":
        return check_agent(args)
    if args.command == "install":
        return install_agent(args)
    if args.command == "suggest-targets":
        return suggest_targets(args)
    if args.command == "run":
        return run_trace(args)
    if args.command == "load":
        return load_trace(args)
    if args.command == "slice":
        return slice_trace_cmd(args)
    if args.command == "explain":
        return explain_cmd(args)
    if args.command == "reverse":
        return reverse_cmd(args)
    if args.command == "replay":
        return replay_cmd(args)
    if args.command == "align":
        return align_cmd(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
