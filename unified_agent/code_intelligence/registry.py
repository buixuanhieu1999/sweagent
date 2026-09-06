"""Lazy adapter registry for code-intelligence capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class CodeCapabilityAdapter(Protocol):
    id: str

    def supports(self, path: Path, operation: str) -> bool: ...

    def execute(self, operation: str, **kwargs): ...


class CodeIntelligenceRegistry:
    def __init__(self, adapters: list[CodeCapabilityAdapter]):
        self.adapters = adapters

    def resolve(self, path: Path, operation: str) -> CodeCapabilityAdapter | None:
        return next(
            (adapter for adapter in self.adapters if adapter.supports(path, operation)),
            None,
        )
