#!/usr/bin/env python3
"""Compatibility launcher. The interactive runtime lives in unified_agent."""

from unified_agent.cli import entrypoint, main, parse_args
from unified_agent.legacy import (
    arguments_for,
    chat,
    clipped,
    load_dotenv,
    run_bash,
    save_trajectory,
    select_shell,
)
from unified_agent.tools import DEFINITIONS

__all__ = [
    "main",
    "parse_args",
    "arguments_for",
    "chat",
    "clipped",
    "load_dotenv",
    "run_bash",
    "save_trajectory",
    "select_shell",
    "tool_definitions",
]


def tool_definitions():
    return DEFINITIONS


if __name__ == "__main__":
    raise SystemExit(entrypoint())
