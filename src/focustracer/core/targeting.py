from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


def _module_name_for_path(project_root: Path, file_path: Path) -> str:
    relative = file_path.resolve().relative_to(project_root.resolve())
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _safe_sorted(values: Iterable[Any]) -> list[Any]:
    return sorted(set(values), key=lambda value: str(value))


@dataclass(slots=True)
class TargetManifest:
    functions: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    thread_names: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TargetManifest":
        data = data or {}
        return cls(
            functions=[str(value) for value in data.get("functions", []) if str(value).strip()],
            files=[str(value) for value in data.get("files", []) if str(value).strip()],
            lines=[str(value) for value in data.get("lines", []) if str(value).strip()],
            thread_names=[
                str(value) for value in data.get("thread_names", []) if str(value).strip()
            ],
        ).normalized()

    @classmethod
    def from_cli(
        cls,
        functions: list[str] | None = None,
        files: list[str] | None = None,
        lines: list[str] | None = None,
        thread_names: list[str] | None = None,
    ) -> "TargetManifest":
        return cls(
            functions=list(functions or []),
            files=list(files or []),
            lines=list(lines or []),
            thread_names=list(thread_names or []),
        ).normalized()

    def normalized(self) -> "TargetManifest":
        return TargetManifest(
            functions=_safe_sorted(value.strip() for value in self.functions if value.strip()),
            files=_safe_sorted(value.strip() for value in self.files if value.strip()),
            lines=_safe_sorted(value.strip() for value in self.lines if value.strip()),
            thread_names=_safe_sorted(
                value.strip() for value in self.thread_names if value.strip()
            ),
        )

    def merge(self, *others: "TargetManifest") -> "TargetManifest":
        manifest = self
        for other in others:
            manifest = TargetManifest(
                functions=manifest.functions + other.functions,
                files=manifest.files + other.files,
                lines=manifest.lines + other.lines,
                thread_names=manifest.thread_names + other.thread_names,
            ).normalized()
        return manifest

    def has_targets(self) -> bool:
        return bool(self.functions or self.files or self.lines or self.thread_names)

    def requires_function_targets(self) -> bool:
        return not bool(self.functions)

    def to_dict(self) -> dict[str, list[str]]:
        manifest = self.normalized()
        return {
            "functions": manifest.functions,
            "files": manifest.files,
            "lines": manifest.lines,
            "thread_names": manifest.thread_names,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass(slots=True)
class CodeInventory:
    project_root: str
    target_script: str
    functions: list[str] = field(default_factory=list)
    loops: list[dict[str, Any]] = field(default_factory=list)
    thread_entries: list[dict[str, Any]] = field(default_factory=list)

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root,
            "target_script": self.target_script,
            "functions": self.functions,
            "loops": self.loops,
            "thread_entries": self.thread_entries,
        }


class _InventoryVisitor(ast.NodeVisitor):
    def __init__(self, module_name: str, rel_path: str):
        self.module_name = module_name
        self.rel_path = rel_path
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.functions: list[str] = []
        self.loops: list[dict[str, Any]] = []
        self.thread_entries: list[dict[str, Any]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qual_parts = [self.module_name, *self.class_stack, node.name]
        qualname = ".".join(part for part in qual_parts if part)
        self.functions.append(qualname)
        self.function_stack.append(qualname)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_For(self, node: ast.For) -> None:
        self._record_loop(node, "for")
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._record_loop(node, "while")
        self.generic_visit(node)

    def _record_loop(self, node: ast.For | ast.While, loop_type: str) -> None:
        self.loops.append(
            {
                "file": self.rel_path,
                "line": node.lineno,
                "type": loop_type,
                "function": self.function_stack[-1] if self.function_stack else self.module_name,
            }
        )

    def visit_Call(self, node: ast.Call) -> None:
        if self._is_thread_constructor(node):
            thread_name = self._extract_constant_keyword(node, "name")
            target_name = self._extract_thread_target(node)
            if thread_name or target_name:
                self.thread_entries.append(
                    {
                        "file": self.rel_path,
                        "line": node.lineno,
                        "name": thread_name,
                        "target": target_name,
                    }
                )
        self.generic_visit(node)

    @staticmethod
    def _is_thread_constructor(node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr == "Thread"
        if isinstance(func, ast.Name):
            return func.id == "Thread"
        return False

    @staticmethod
    def _extract_constant_keyword(node: ast.Call, keyword_name: str) -> str | None:
        for keyword in node.keywords:
            if keyword.arg == keyword_name and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    return keyword.value.value
        return None

    @staticmethod
    def _extract_thread_target(node: ast.Call) -> str | None:
        for keyword in node.keywords:
            if keyword.arg != "target":
                continue
            value = keyword.value
            if isinstance(value, ast.Name):
                return value.id
            if isinstance(value, ast.Attribute):
                if isinstance(value.value, ast.Name):
                    return f"{value.value.id}.{value.attr}"
                return value.attr
        return None


def build_code_inventory(project_root: str | Path, target_script: str | Path) -> CodeInventory:
    root_path = Path(project_root).resolve()
    target_script_path = Path(target_script).resolve()

    # Per user requirement: Only scan the selected target_script, not the entire project directory.
    python_files = []
    if target_script_path.exists() and target_script_path.suffix == ".py":
        python_files.append(target_script_path)

    functions: list[str] = []
    loops: list[dict[str, Any]] = []
    thread_entries: list[dict[str, Any]] = []

    for file_path in python_files:
        # Read source — handle non-UTF-8 files gracefully
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        except OSError:
            continue

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            continue

        try:
            module_name = _module_name_for_path(root_path, file_path)
        except ValueError:
            module_name = file_path.stem
        try:
            rel_path = str(file_path.resolve().relative_to(root_path))
        except ValueError:
            rel_path = file_path.name

        visitor = _InventoryVisitor(module_name=module_name, rel_path=rel_path)
        visitor.visit(tree)
        functions.extend(visitor.functions)
        loops.extend(visitor.loops)
        thread_entries.extend(visitor.thread_entries)

    return CodeInventory(
        project_root=str(root_path),
        target_script=str(target_script_path),
        functions=_safe_sorted(functions),
        loops=sorted(loops, key=lambda item: (item["file"], item["line"], item["type"])),
        thread_entries=sorted(
            thread_entries,
            key=lambda item: (
                item["file"],
                item["line"],
                item.get("name") or "",
                item.get("target") or "",
            ),
        ),
    )


def parse_line_filters(
    line_filters: Iterable[str | int] | None,
) -> tuple[set[int], dict[str, set[int]]]:
    global_lines: set[int] = set()
    file_lines: dict[str, set[int]] = {}

    for item in line_filters or []:
        if isinstance(item, int):
            global_lines.add(item)
            continue

        value = str(item).strip()
        if not value:
            continue
        if ":" not in value:
            global_lines.add(int(value))
            continue

        file_part, line_part = value.rsplit(":", 1)
        file_key = str(Path(file_part).as_posix())
        file_lines.setdefault(file_key, set()).add(int(line_part))

    return global_lines, file_lines
