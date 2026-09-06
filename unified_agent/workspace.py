"""Workspace boundaries and startup facts, deliberately free of project semantics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .repo import EXCLUDED, read_text


@dataclass(frozen=True)
class WorkspaceContext:
    """The directory where the agent works and its enclosing worktree, if any."""

    cwd: Path
    roots: tuple[Path, ...]
    git_root: Path | None
    instruction_chain: tuple[Path, ...]
    trust: str = "local"

    def facts(self, *, include_tree: bool = True) -> dict:
        result = {
            "cwd": str(self.cwd),
            "roots": [str(root) for root in self.roots],
            "git_root": str(self.git_root) if self.git_root else None,
            "instruction_files": [
                path.relative_to(self.git_root or self.cwd).as_posix()
                for path in self.instruction_chain
            ],
            "trust": self.trust,
        }
        if include_tree:
            result["shallow_tree"] = shallow_tree(self.cwd)
        return result


def git_root(cwd: Path) -> Path | None:
    """Find an enclosing Git worktree without running a project command."""
    cwd = cwd.resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def instruction_chain(cwd: Path, root: Path | None) -> tuple[Path, ...]:
    start = root or cwd
    try:
        relative = cwd.relative_to(start)
    except ValueError:
        return ()
    paths = []
    current = start
    candidate = current / "AGENTS.md"
    if candidate.is_file():
        paths.append(candidate)
    for part in relative.parts:
        current /= part
        candidate = current / "AGENTS.md"
        if candidate.is_file():
            paths.append(candidate)
    return tuple(paths)


def shallow_tree(cwd: Path, limit: int = 200) -> list[str]:
    return [
        (path.name + ("/" if path.is_dir() else ""))
        for path in sorted(
            cwd.iterdir(), key=lambda item: (not item.is_dir(), item.name)
        )
        if path.name not in EXCLUDED and not path.name.startswith(".env")
    ][:limit]


def context(cwd: Path) -> WorkspaceContext:
    cwd = cwd.resolve()
    root = git_root(cwd)
    roots = (root,) if root else (cwd,)
    return WorkspaceContext(cwd, roots, root, instruction_chain(cwd, root))


def instructions(value: WorkspaceContext) -> str:
    """Load only the instruction files whose directory scopes include `cwd`."""
    root = value.git_root or value.cwd
    sections = []
    for path in value.instruction_chain:
        scope = path.parent.relative_to(root).as_posix() or "."
        sections.append(f"Scope: {scope}/\n{read_text(path, 64000)}")
    return "\n\n".join(sections)


def inspect(root: Path) -> dict:
    """Compatibility entry point for persisted older tool trajectories."""
    return context(root).facts()
