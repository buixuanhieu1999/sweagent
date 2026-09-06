"""Compatibility helpers retained for the original agent.py API."""

from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 12000


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE pairs without adding a dependency or overwriting real env vars."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if (
            key in {"OLLAMA_API_KEY", "OLLAMA_HOST", "OLLAMA_MODEL"}
            and key not in os.environ
        ):
            os.environ[key] = value


def chat(host: str, api_key: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    url = host.rstrip("/") + "/chat"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not reach Ollama at {url}: {error.reason}"
        ) from error


def clipped(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return (
        value[:MAX_OUTPUT_CHARS]
        + f"\n\n[output truncated after {MAX_OUTPUT_CHARS} characters]"
    )


def select_shell(selection: str) -> tuple[str, list[str]]:
    """Choose a real shell for each independent command execution."""
    if os.name != "nt":
        if selection in ("auto", "bash"):
            return "Bash", ["/bin/bash", "-lc"]
        if selection == "powershell":
            return "PowerShell", [
                "pwsh",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
            ]
        return "sh", ["/bin/sh", "-c"]
    git_bash = next(
        (
            Path(p)
            for p in (
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe",
            )
            if Path(p).is_file()
        ),
        None,
    )
    if selection == "bash" and not git_bash:
        raise RuntimeError(
            "Git Bash was not found. Install Git for Windows or use --shell powershell."
        )
    if selection == "bash" or (selection == "auto" and git_bash):
        return "Git Bash", [str(git_bash), "-lc"]
    if selection in ("auto", "powershell"):
        return "PowerShell", [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
        ]
    return "cmd.exe", ["cmd.exe", "/d", "/s", "/c"]


def arguments_for(call: dict[str, Any]) -> dict[str, Any]:
    arguments = call.get("function", {}).get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    return arguments if isinstance(arguments, dict) else {}


def save_trajectory(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def run_bash(
    command: str, repo: Path, timeout: int, dry_run: bool, shell_prefix: list[str]
) -> str:
    if dry_run:
        return "[dry-run: command not executed]"
    from .terminal import execute

    result = execute([*shell_prefix, command], repo, timeout)
    prefix = (
        f"command timed out after {timeout}s"
        if result.get("timed_out")
        else f"exit code: {result['exit_code']}"
    )
    return clipped(prefix + "\n" + result["output"])
