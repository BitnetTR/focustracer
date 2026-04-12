from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generator


class BaseAIAgent(ABC):
    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_stream(self, prompt: str, **kwargs) -> Generator[str, None, None]:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def suggest_targets(
        self,
        inventory: dict[str, Any],
        *,
        manual_targets: dict[str, Any] | None = None,
        error_context: str | None = None,
        user_hint: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def analyze_trace(
        self,
        trace_file: str,
        source_file: str,
        *,
        error_context: str | None = None,
    ) -> str:
        raise NotImplementedError

    def is_available(self) -> bool:
        return bool(self.health().get("ok"))
