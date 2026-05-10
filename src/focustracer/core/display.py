"""
Trace Display
=============
:class:`TraceDocument` içeriğini ``rich`` kütüphanesi ile terminal'de gösterir.
``focustracer load`` komutu tarafından kullanılır.

Varsayılan çıktı: hiyerarşik rich call tree.
``summary_only=True`` ile sadece istatistik tablosu gösterilir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.tree import Tree
    from rich import box as rich_box

    HAS_RICH = True
except ImportError:  # pragma: no cover
    HAS_RICH = False

from focustracer.core.loader import TraceDocument


# ---------------------------------------------------------------------------
# Emoji / label constants
# ---------------------------------------------------------------------------

_ICON_SCOPE = "🔷"
_ICON_LOOP = "🔁"
_ICON_THREAD = "📡"
_ICON_RETURN = "↩️ "
_ICON_EXCEPTION = "💥"
_ICON_EVENT_LINE = "·"
_ICON_DELTA = "📈"


# ---------------------------------------------------------------------------
# Main displayer
# ---------------------------------------------------------------------------

class TraceDisplayer:
    """
    :class:`TraceDocument`'ı terminal'de görselleştirir.

    Kullanım::

        displayer = TraceDisplayer()
        displayer.display(doc)
        displayer.display(doc, summary_only=True)
    """

    def __init__(self, console: Optional[Any] = None) -> None:
        self.console: Any
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def display(
        self,
        doc: TraceDocument,
        summary_only: bool = False,
        filter_function: Optional[str] = None,
        filter_thread: Optional[str] = None,
    ) -> None:
        self._display_header(doc)
        self._display_stats(doc)
        if not summary_only:
            self._display_tree(doc, filter_function=filter_function, filter_thread=filter_thread)

    # ------------------------------------------------------------------
    # Header panel
    # ------------------------------------------------------------------

    def _display_header(self, doc: TraceDocument) -> None:
        fname = Path(doc.source_path).name
        dur = f"{doc.total_duration:.4f}s"
        threads = doc.count_threads() or 1  # v1 traces have no thread nodes

        info = (
            f"[bold cyan]File:[/bold cyan] {fname}\n"
            f"[bold cyan]Schema:[/bold cyan] v{doc.schema_version}  "
            f"[bold cyan]Duration:[/bold cyan] {dur}  "
            f"[bold cyan]Events:[/bold cyan] {doc.total_events}  "
            f"[bold cyan]Threads:[/bold cyan] {threads}"
        )

        if HAS_RICH and self.console:
            self.console.print(
                Panel(info, title="[bold white]FocusTracer — Trace Analysis[/bold white]",
                      border_style="bright_blue", padding=(0, 2))
            )
        else:
            print(f"\n{'='*60}")
            print(f"  FocusTracer — Trace Analysis")
            print(f"  File:     {fname}")
            print(f"  Schema:   v{doc.schema_version}")
            print(f"  Duration: {dur}  Events: {doc.total_events}  Threads: {threads}")
            print(f"{'='*60}")

    # ------------------------------------------------------------------
    # Statistics table
    # ------------------------------------------------------------------

    def _display_stats(self, doc: TraceDocument) -> None:
        counts = doc.event_type_counts()

        if HAS_RICH and self.console:
            table = Table(
                title="📊 Event Statistics",
                box=rich_box.SIMPLE_HEAD,
                show_header=True,
                header_style="bold magenta",
                padding=(0, 2),
            )
            for etype in ("call", "line", "return", "exception"):
                table.add_column(etype, justify="center")
            table.add_row(*[str(counts.get(e, 0)) for e in ("call", "line", "return", "exception")])

            # Targets (v2.2)
            if doc.targets:
                tgt_names = ", ".join(
                    f"[green]{t['name']}[/green]" for t in doc.targets[:8]
                )
                if len(doc.targets) > 8:
                    tgt_names += f" [dim](+{len(doc.targets) - 8} more)[/dim]"
                self.console.print(table)
                self.console.print(f"  [bold cyan]Targets:[/bold cyan] {tgt_names}\n")
            else:
                self.console.print(table)
                self.console.print()
        else:
            print(f"\n  call={counts.get('call',0)}  line={counts.get('line',0)}  "
                  f"return={counts.get('return',0)}  exception={counts.get('exception',0)}")
            if doc.targets:
                names = ", ".join(t["name"] for t in doc.targets[:8])
                print(f"  Targets: {names}")
            print()

    # ------------------------------------------------------------------
    # Execution tree
    # ------------------------------------------------------------------

    def _display_tree(
        self,
        doc: TraceDocument,
        filter_function: Optional[str] = None,
        filter_thread: Optional[str] = None,
    ) -> None:
        nodes = doc.nodes

        # Apply thread filter at top level
        if filter_thread:
            nodes = [
                n for n in nodes
                if n.get("type") != "thread" or n.get("id") == filter_thread or n.get("name") == filter_thread
            ]

        if HAS_RICH and self.console:
            tree = Tree("🔍 [bold white]Execution Tree[/bold white]")
            for node in nodes:
                self._build_rich_node(tree, node, filter_function=filter_function)
            self.console.print(tree)
        else:
            print("  Execution Tree")
            for node in nodes:
                self._print_plain_node(node, indent=2, filter_function=filter_function)
            print()

    # ------------------------------------------------------------------
    # Rich tree builders
    # ------------------------------------------------------------------

    def _build_rich_node(
        self,
        parent: Any,
        node: dict[str, Any],
        filter_function: Optional[str] = None,
    ) -> None:
        ntype = node.get("type")

        if ntype == "thread":
            self._build_rich_thread(parent, node, filter_function)
        elif ntype == "scope":
            self._build_rich_scope(parent, node, filter_function)
        elif ntype == "loop":
            self._build_rich_loop(parent, node, filter_function)
        elif ntype == "event":
            self._build_rich_event(parent, node)

    def _build_rich_thread(
        self, parent: Any, node: dict[str, Any], filter_function: Optional[str]
    ) -> None:
        tid = node.get("id", "?")
        tname = node.get("name", "")
        label = f"{_ICON_THREAD} [bold yellow]Thread-{tid}[/bold yellow]"
        if tname:
            label += f' [dim]"{tname}"[/dim]'
        branch = parent.add(label)
        for child in node.get("children", []):
            self._build_rich_node(branch, child, filter_function)

    def _build_rich_scope(
        self, parent: Any, node: dict[str, Any], filter_function: Optional[str]
    ) -> None:
        fn = node.get("function", "?")

        # Apply function filter — still recurse into children
        if filter_function and filter_function not in fn:
            for child in node.get("children", []):
                self._build_rich_node(parent, child, filter_function)
            return

        # Build label
        args = node.get("arguments", {})
        args_str = ", ".join(
            f"[cyan]{k}[/cyan]=[italic]{v[0]}[/italic]"
            for k, v in (args.items() if isinstance(args, dict) else [])
        )
        label = f"{_ICON_SCOPE} [bold green]{fn}[/bold green]([cyan]{args_str}[/cyan])"

        # Duration (v2.2)
        dur = node.get("duration")
        if dur is not None:
            label += f"  [dim]{dur * 1000:.2f}ms[/dim]"

        branch = parent.add(label)

        # Children
        for child in node.get("children", []):
            self._build_rich_node(branch, child, filter_function)

        # Return value
        rv = node.get("return_value")
        if rv is not None:
            val, typ = rv if isinstance(rv, tuple) else (str(rv), "")
            branch.add(f"{_ICON_RETURN} [dim]return[/dim] [yellow]{val}[/yellow] [dim]{typ}[/dim]")

        # Exception
        exc = node.get("exception")
        if exc:
            exc_label = (
                f"{_ICON_EXCEPTION} [bold red]{exc.get('type','?')}[/bold red]: "
                f"[red]{exc.get('value','')}[/red]"
            )
            exc_branch = branch.add(exc_label)
            tb = exc.get("traceback", "")
            if tb:
                for line in tb.strip().splitlines()[:6]:
                    exc_branch.add(f"[dim]{line.strip()}[/dim]")

    def _build_rich_loop(
        self, parent: Any, node: dict[str, Any], filter_function: Optional[str]
    ) -> None:
        src = node.get("source", "loop")
        total = node.get("iterations", 0)
        truncated = node.get("truncated_iterations", 0)

        iter_info = f"{total} iter"
        if truncated:
            iter_info += f" [dim]({truncated} truncated)[/dim]"

        label = f"{_ICON_LOOP} [bold magenta]{src}[/bold magenta]  [dim]{iter_info}[/dim]"
        branch = parent.add(label)

        # Per-iteration children
        for iter_obj in node.get("iteration_list", []):
            idx = iter_obj.get("index", 0)
            iter_branch = branch.add(f"[dim][{idx}][/dim]")
            for child in iter_obj.get("events", []):
                self._build_rich_node(iter_branch, child, filter_function)

        # Loop summary (variable changes)
        summary = node.get("summary", {})
        if summary:
            parts = [
                f"[cyan]{name}[/cyan]: [dim]{info['initial']}[/dim] → [yellow]{info['final']}[/yellow]"
                for name, info in summary.items()
            ]
            branch.add(f"{_ICON_DELTA} " + "  │  ".join(parts))

    def _build_rich_event(self, parent: Any, node: dict[str, Any]) -> None:
        data = node.get("data", {})
        etype = data.get("event_type", "")

        # Only show call/return/exception events inline; skip line noise
        if etype == "line":
            delta = data.get("delta", [])
            if not delta:
                return
            parts = []
            for ch in delta:
                action = ch.get("action", "")
                name = ch.get("name", "")
                if action == "added":
                    parts.append(f"[green]+{name}[/green]={ch.get('new','')}")
                elif action == "changed":
                    parts.append(f"[yellow]{name}[/yellow]: {ch.get('old','')}→{ch.get('new','')}")
                elif action == "removed":
                    parts.append(f"[red]-{name}[/red]")
            if parts:
                parent.add(f"[dim]L{data.get('line','')}[/dim] " + "  ".join(parts))
        elif etype == "exception":
            exc = data.get("exception") or {}
            parent.add(
                f"{_ICON_EXCEPTION} [bold red]{exc.get('type','?')}[/bold red]: "
                f"[red]{exc.get('value','')}[/red]"
            )

    # ------------------------------------------------------------------
    # Plain-text fallback (no rich)
    # ------------------------------------------------------------------

    def _print_plain_node(
        self,
        node: dict[str, Any],
        indent: int,
        filter_function: Optional[str],
    ) -> None:
        pad = " " * indent
        ntype = node.get("type")

        if ntype == "thread":
            print(f"{pad}Thread-{node.get('id','')} \"{node.get('name','')}\"")
            for child in node.get("children", []):
                self._print_plain_node(child, indent + 2, filter_function)

        elif ntype == "scope":
            fn = node.get("function", "?")
            if filter_function and filter_function not in fn:
                for child in node.get("children", []):
                    self._print_plain_node(child, indent, filter_function)
                return
            args = node.get("arguments", {})
            args_str = ", ".join(
                f"{k}={v[0]}" for k, v in (args.items() if isinstance(args, dict) else [])
            )
            dur = node.get("duration")
            dur_str = f"  ({dur*1000:.2f}ms)" if dur else ""
            print(f"{pad}[scope] {fn}({args_str}){dur_str}")
            for child in node.get("children", []):
                self._print_plain_node(child, indent + 2, filter_function)
            rv = node.get("return_value")
            if rv:
                print(f"{pad}  return {rv[0]}")

        elif ntype == "loop":
            src = node.get("source", "loop")
            total = node.get("iterations", 0)
            print(f"{pad}[loop] {src}  ({total} iter)")
            summary = node.get("summary", {})
            for name, info in summary.items():
                print(f"{pad}  {name}: {info['initial']} -> {info['final']}")

        elif ntype == "event":
            data = node.get("data", {})
            if data.get("event_type") == "exception":
                exc = data.get("exception") or {}
                print(f"{pad}[exception] {exc.get('type','?')}: {exc.get('value','')}")
