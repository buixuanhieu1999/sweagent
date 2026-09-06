"""Generic code-intelligence API; callers never choose a language adapter."""

from __future__ import annotations

from pathlib import Path

from .. import lsp, search
from ..repo import files, read_text, safe_path


class CodeIntelligenceService:
    def __init__(self, root: Path, config: dict):
        self.root = root.resolve()
        self.config = config

    def _path(self, name: str) -> Path:
        return safe_path(self.root, name)

    def _command(self, path: Path) -> list[str]:
        settings = self.config.get("lsp", {})
        servers = settings.get("servers", {})
        if not isinstance(servers, dict):
            raise ValueError("lsp.servers must map language IDs to argv lists")
        command = servers.get(lsp.language_id(path)) or servers.get(path.suffix)
        command = command or settings.get("command", [])
        if not isinstance(command, list) or not all(
            isinstance(item, str) for item in command
        ):
            raise ValueError("LSP server command must be an argv list")
        return command

    def configured_command(self, path: str) -> list[str]:
        return self._command(self._path(path))

    def _lsp_or_none(self, operation: str, path: Path, line: int, character: int):
        command = self._command(path)
        if not command:
            return None
        try:
            language_root = self.language_root(path)
            return {
                "backend": "lsp",
                "language_root": str(language_root),
                "result": lsp.query(
                    language_root, path, command, operation, line, character
                ),
            }
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            return {"backend": "generic", "lsp_error": str(exc)}

    def language_root(self, path: Path) -> Path:
        """Use the nearest project metadata directory if the adapter needs it."""
        markers = {
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "*.csproj",
        }
        for candidate in (path.parent, *path.parent.parents):
            if not candidate.is_relative_to(self.root):
                break
            if any(
                (candidate / marker).exists()
                for marker in markers
                if not marker.startswith("*")
            ) or any(candidate.glob("*.csproj")):
                return candidate
        return self.root

    def definition(self, path: str, line: int = 1, character: int = 1) -> dict:
        source = self._path(path)
        result = self._lsp_or_none("definition", source, line, character)
        if result and result.get("backend") == "lsp":
            return result
        token = self._token_at(source, line, character)
        return {
            **(result or {}),
            "backend": "generic",
            "query": token,
            "result": search.symbols(self.root, token) if token else [],
        }

    def references(self, path: str, line: int = 1, character: int = 1) -> dict:
        source = self._path(path)
        result = self._lsp_or_none("references", source, line, character)
        if result and result.get("backend") == "lsp":
            return result
        token = self._token_at(source, line, character)
        return {
            **(result or {}),
            "backend": "generic",
            "query": token,
            "result": self._text_references(token),
        }

    def symbols(self, query: str = "", path: str | None = None) -> dict:
        result = search.symbols(self.root, query)
        if path:
            source = self._path(path)
            relative = source.relative_to(self.root).as_posix()
            result = [row for row in result if row["path"] == relative]
        return {"backend": "generic", "result": result}

    def structure(self, path: str) -> dict:
        source = self._path(path)
        relative = source.relative_to(self.root).as_posix()
        return {
            "backend": "generic",
            "path": relative,
            "symbols": [
                row for row in search.symbols(self.root) if row["path"] == relative
            ],
        }

    def diagnostics(self, path: str) -> dict:
        source = self._path(path)
        result = self._lsp_or_none("diagnostics", source, 1, 1)
        return result or {
            "backend": "generic",
            "available": False,
            "message": "No language server is configured for this file.",
        }

    def _token_at(self, path: Path, line: int, character: int) -> str:
        lines = read_text(path).splitlines()
        if line < 1 or line > len(lines):
            raise ValueError("line is outside the file")
        text = lines[line - 1]
        offset = max(0, min(len(text), character - 1))
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$"
        start = offset
        while start > 0 and text[start - 1] in allowed:
            start -= 1
        end = offset
        while end < len(text) and text[end] in allowed:
            end += 1
        return text[start:end]

    def _text_references(self, token: str) -> list[dict]:
        if not token:
            return []
        result = []
        for path in files(self.root):
            try:
                for line, text in enumerate(read_text(path).splitlines(), 1):
                    if token in text:
                        result.append(
                            {
                                "path": path.relative_to(self.root).as_posix(),
                                "line": line,
                                "text": text[:500],
                            }
                        )
                        if len(result) == 200:
                            return result
            except (OSError, ValueError):
                continue
        return result
