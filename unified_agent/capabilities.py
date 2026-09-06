"""Declarative capability metadata for tools, subagents, and skills."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class Capability:
    name: str
    kind: Literal["tool", "subagent", "skill"]
    description: str
    cost: Literal["low", "medium", "high"] = "low"
    side_effects: tuple[str, ...] = ()

    def public(self) -> dict:
        return asdict(self) | {"side_effects": list(self.side_effects)}


class CapabilityRegistry:
    def __init__(self):
        self._items: dict[str, Capability] = {}

    def register(self, capability: Capability):
        if capability.name in self._items:
            raise ValueError(f"Capability already registered: {capability.name}")
        self._items[capability.name] = capability

    def get(self, name: str) -> Capability:
        return self._items[name]

    def list(self, kind: str | None = None) -> list[Capability]:
        return [
            item for item in self._items.values() if kind is None or item.kind == kind
        ]
