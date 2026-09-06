"""Discoverable, opt-in procedural guidance. Skills never select a workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path


BUILTIN = Path(__file__).with_name("builtin_skills")


def _parse(path: Path) -> Skill | None:
    text = path.read_text(encoding="utf-8-sig")
    name = path.parent.name.replace("_", "-")
    description = next(
        (
            line.removeprefix("description:").strip()
            for line in text.splitlines()
            if line.startswith("description:")
        ),
        "",
    )
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        return None
    return Skill(name, description or "Reusable coding guidance", path)


def discover(root: Path) -> dict[str, Skill]:
    result: dict[str, Skill] = {}
    for base in (BUILTIN, root / ".agent" / "skills"):
        if not base.exists():
            continue
        for path in base.glob("*/SKILL.md"):
            skill = _parse(path)
            if skill:
                result[skill.name] = skill
    return result


def load(root: Path, name: str) -> dict:
    skills = discover(root)
    if name not in skills:
        raise ValueError(f"Unknown skill: {name}")
    skill = skills[name]
    text = skill.path.read_text(encoding="utf-8-sig")
    if len(text) > 24000:
        raise ValueError("Skill exceeds 24,000 characters")
    return {"name": skill.name, "description": skill.description, "content": text}
