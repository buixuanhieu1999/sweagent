"""Small plugin interface for deferred, project-local tool extensions."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol


Exposure = Literal["direct", "deferred"]


@dataclass(frozen=True)
class ExtensionTool:
    name: str
    description: str
    parameters: dict
    executor: Callable[[dict], object]
    exposure: Exposure = "deferred"
    action: str = "read"


class ToolExtension(Protocol):
    def tools(self) -> list[ExtensionTool]: ...


def discover(root: Path) -> list[ExtensionTool]:
    result = []
    for path in sorted((root / ".agent" / "extensions").glob("*.py")):
        spec = importlib.util.spec_from_file_location(
            "agent_extension_" + path.stem, path
        )
        if not spec or not spec.loader:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        extension = getattr(module, "extension", None)
        if extension is None or not callable(getattr(extension, "tools", None)):
            raise ValueError(f"Extension {path.name} must export extension.tools()")
        for tool in extension.tools():
            if not isinstance(tool, ExtensionTool):
                raise ValueError(f"Extension {path.name} returned an invalid tool")
            if (
                not tool.name
                or not tool.name.replace(".", "").replace("_", "").isalnum()
            ):
                raise ValueError(f"Extension {path.name} has an invalid tool name")
            result.append(tool)
    return result
