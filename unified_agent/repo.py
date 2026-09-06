from __future__ import annotations

import fnmatch
import os
from pathlib import Path

EXCLUDED = {
    ".git",
    ".agent",
    ".mini-swe",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
}

# Text formats supported by optional source-intelligence fallbacks. A project
# can contain several formats; workspace context itself does not use this map.
SOURCE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".cs": "C#",
    ".fs": "F#",
    ".fsx": "F#",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".h": "C/C++",
    ".hpp": "C++",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".scala": "Scala",
    ".sc": "Scala",
    ".clj": "Clojure",
    ".cljs": "ClojureScript",
    ".hs": "Haskell",
    ".lua": "Lua",
    ".jl": "Julia",
    ".r": "R",
    ".R": "R",
    ".sh": "Shell",
    ".ps1": "PowerShell",
    ".sql": "SQL",
}


def safe_path(root: Path, name: str, *, internal: bool = False) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Path escapes the project root")
    relative = path.relative_to(root.resolve())
    if not internal and any(
        part in {".git", ".agent", ".mini-swe"} for part in relative.parts
    ):
        raise ValueError(
            "Agent state and Git internals are protected; use artifact/git tools"
        )
    return path


def files(root: Path, pattern: str = "*", limit: int = 10000):
    count = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in EXCLUDED
            and not d.endswith(".egg-info")
            and not (Path(directory) / d).is_symlink()
            and (Path(directory) / d).resolve().is_relative_to(root.resolve())
        )
        for name in sorted(names):
            path = Path(directory) / name
            if (
                path.is_symlink()
                or name == ".env"
                or name.startswith(".env.")
                and name != ".env.example"
            ):
                continue
            rel = path.relative_to(root).as_posix()
            if fnmatch.fnmatch(rel, pattern) or Path(rel).match(pattern):
                yield path
                count += 1
                if count >= limit:
                    return


def read_text(path: Path, max_bytes: int = 1_000_000) -> str:
    if path.stat().st_size > max_bytes:
        raise ValueError(f"File exceeds {max_bytes} bytes; narrow the request")
    data = path.read_bytes()
    if b"\0" in data:
        raise ValueError("Binary file")
    return data.decode("utf-8-sig")


def instructions(root: Path) -> str:
    sections = []
    for path in files(root, "AGENTS.md"):
        text = read_text(path, 64000)
        sections.append(
            f"Scope: {path.parent.relative_to(root).as_posix()}/ (deeper scopes override)\n{text}"
        )
    return "\n\n".join(sections)


def bootstrap(root: Path) -> dict:
    paths = [p.relative_to(root).as_posix() for p in files(root, limit=2000)]
    source = any(Path(p).suffix in SOURCE_EXTENSIONS for p in paths)
    markers = {
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "requirements.txt",
        "Package.swift",
        "mix.exs",
        "pubspec.yaml",
        "build.sbt",
        "CMakeLists.txt",
        "Gemfile",
        "composer.json",
    }
    return {
        "exists": (root / ".git").exists()
        or source
        or bool(markers.intersection(paths)),
        "files": paths[:150],
        "file_count_at_least": len(paths),
    }
