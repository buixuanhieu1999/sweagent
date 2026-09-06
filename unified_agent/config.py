from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_HOST = "https://ollama.com/api"
DEFAULT_MODEL = "gemma4:31b"


def load_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError(
                "YAML config requires: python -m pip install -e ."
            ) from exc
        value = yaml.safe_load(text)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected a mapping in {path}")
    return value


def load_config(repo: Path) -> dict[str, Any]:
    config = load_mapping(repo / ".agent" / "config.yaml")
    defaults = {
        "provider": {
            "type": "ollama",
            "host": DEFAULT_HOST,
            "model": DEFAULT_MODEL,
            "stream": True,
            "keep_alive": "10m",
            "timeout": 180,
        },
        "agent": {"max_steps": 40, "role_steps": 10, "command_timeout": 120},
        "compaction": {"enabled": True, "max_chars": 64000, "recent_messages": 12},
        "models": {},
        "validation": {},
        "execution": {"backend": "local"},
        "permissions": {
            "file": ".agent/rules.yaml",
            "user_file": "~/.config/unified-agent/rules.yaml",
            "access_profile": "workspace",
            "approval_policy": "on-request",
        },
        "lsp": {},
    }
    for key, values in defaults.items():
        section = config.setdefault(key, {})
        if not isinstance(section, dict):
            raise ValueError(f"Config section {key} must be a mapping")
        for name, value in values.items():
            section.setdefault(name, value)
    if config["provider"]["type"] != "ollama":
        raise ValueError("Only the Ollama provider is currently implemented")
    for env, name in (("OLLAMA_HOST", "host"), ("OLLAMA_MODEL", "model")):
        if os.getenv(env):
            config["provider"][name] = os.environ[env]
    return config
