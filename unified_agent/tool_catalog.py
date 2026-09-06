"""Metadata-only catalog used to decide which tool schemas reach a model turn."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Exposure(StrEnum):
    DIRECT = "direct"
    DEFERRED = "deferred"
    HIDDEN = "hidden"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    category: str
    exposure: Exposure = Exposure.DIRECT
    requirements: tuple[str, ...] = ()


DEFERRED = {
    "bm25",
    "ast",
    "graph",
    "lsp",
    "localize",
    "coverage",
    "code_definition",
    "code_references",
    "code_symbols",
    "code_structure",
    "code_diagnostics",
    "web_search",
    "web_fetch",
    "mcp_connect",
    "mcp_disconnect",
    "mcp_list_servers",
}


class ToolCatalog:
    def __init__(self, names: list[str], hidden: set[str]):
        self._items = {
            name: ToolDescriptor(
                name,
                name.split("_", 1)[0],
                Exposure.HIDDEN
                if name in hidden
                else Exposure.DEFERRED
                if name in DEFERRED
                else Exposure.DIRECT,
            )
            for name in names
        }

    def search(self, query: str) -> list[ToolDescriptor]:
        terms = set(query.lower().replace(".", "_").split())
        return [
            item
            for item in self._items.values()
            if item.exposure == Exposure.DEFERRED
            and (
                not terms
                or terms.intersection(item.name.lower().replace(".", "_").split("_"))
            )
        ]

    def register(self, descriptor: ToolDescriptor) -> None:
        if descriptor.name in self._items:
            raise ValueError(f"Tool already registered: {descriptor.name}")
        self._items[descriptor.name] = descriptor

    def unregister(self, name: str) -> None:
        self._items.pop(name, None)

    def visible(self, allowed: set[str], enabled: set[str]) -> set[str]:
        return {
            item.name
            for item in self._items.values()
            if item.name in allowed
            and (
                item.exposure == Exposure.DIRECT
                or item.exposure == Exposure.DEFERRED
                and item.name in enabled
            )
        }
