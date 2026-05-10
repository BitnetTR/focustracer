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
    suggest_parser.add_argument("--schema-version", default="2.2")
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
    run_parser.add_argument("--schema-version", default="2.2")
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


def main(argv: Optional[list[str]] = None) -> int:
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
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
