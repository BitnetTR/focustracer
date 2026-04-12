from __future__ import annotations

import importlib
from functools import wraps
from typing import Any, Callable, Optional

from focustracer.core.recorder import TraceRecorder


class DynamicPatcher:
    """
    Runtime monkey patcher for importable functions and bound methods.

    The patcher never edits source files. It replaces callables in memory and
    activates a recorder only while the wrapped target is executing.
    """

    def __init__(self, tracer: TraceRecorder, target_functions: Optional[list[str]] = None):
        self.tracer = tracer
        self.target_functions = set(target_functions or [])
        self._original_functions: dict[str, tuple[Any, str, Callable[..., Any]]] = {}

    def add_target(self, target: str) -> None:
        self.target_functions.add(target)

    def remove_target(self, target: str) -> None:
        self.target_functions.discard(target)

    def _resolve_target(self, target: str) -> tuple[Any, str]:
        parts = target.split(".")
        if len(parts) < 2:
            raise ValueError(f"Target must include a module path: {target}")

        for split_index in range(len(parts) - 1, 0, -1):
            module_name = ".".join(parts[:split_index])
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue

            owner: Any = module
            for attr_name in parts[split_index:-1]:
                owner = getattr(owner, attr_name)
            return owner, parts[-1]

        raise ImportError(f"Cannot import target module for {target}")

    def patch_function(self, target: str) -> bool:
        if target in self._original_functions:
            return True

        try:
            owner, attr_name = self._resolve_target(target)
            original = getattr(owner, attr_name)
            if not callable(original):
                raise TypeError(f"Target is not callable: {target}")

            @wraps(original)
            def wrapped(*args, **kwargs):
                with self.tracer.activate_for_current_thread():
                    return original(*args, **kwargs)

            setattr(owner, attr_name, wrapped)
            self._original_functions[target] = (owner, attr_name, original)
            return True
        except Exception:
            return False

    def patch_all(self) -> dict[str, bool]:
        return {target: self.patch_function(target) for target in sorted(self.target_functions)}

    def unpatch_function(self, target: str) -> bool:
        original = self._original_functions.get(target)
        if original is None:
            return False
        owner, attr_name, callable_obj = original
        setattr(owner, attr_name, callable_obj)
        del self._original_functions[target]
        return True

    def unpatch_all(self) -> None:
        for target in list(self._original_functions):
            self.unpatch_function(target)
