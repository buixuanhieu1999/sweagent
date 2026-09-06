"""Replaceable command execution boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .terminal import execute, start


@dataclass(frozen=True)
class CommandSpec:
    command: str | list[str]
    cwd: Path
    timeout: int
    shell: str = "auto"


@dataclass(frozen=True)
class BackgroundSpec:
    command: str | list[str]
    cwd: Path
    shell: str = "auto"
    log_path: Path | None = None


class ExecutionBackend(Protocol):
    def execute(self, spec: CommandSpec) -> dict: ...

    def start(self, spec: BackgroundSpec) -> dict: ...


class LocalExecutionBackend:
    """Current local-process backend; a sandbox backend can implement this protocol."""

    def execute(self, spec: CommandSpec) -> dict:
        return execute(spec.command, spec.cwd, spec.timeout, spec.shell)

    def start(self, spec: BackgroundSpec) -> dict:
        return start(spec.command, spec.cwd, spec.shell, spec.log_path)
