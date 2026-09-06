"""Small stdio LSP client for explicitly configured language servers."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path

from .repo import read_text


LANGUAGE_IDS = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascriptreact",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".vue": "vue",
    ".svelte": "svelte",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".scala": "scala",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".hs": "haskell",
    ".lua": "lua",
    ".jl": "julia",
    ".r": "r",
    ".R": "r",
    ".sh": "shellscript",
    ".ps1": "powershell",
    ".sql": "sql",
}


def language_id(path: Path) -> str:
    return LANGUAGE_IDS.get(path.suffix, path.suffix.lstrip("."))


def query(
    root: Path,
    path: Path,
    command: list[str],
    operation: str,
    line: int = 1,
    character: int = 1,
    timeout: int = 20,
):
    methods = {
        "definition": "textDocument/definition",
        "references": "textDocument/references",
        "symbols": "textDocument/documentSymbol",
        "hover": "textDocument/hover",
        "diagnostics": "textDocument/diagnostic",
    }
    if operation not in methods:
        raise ValueError("Unknown LSP operation")
    if not command or not all(isinstance(x, str) for x in command):
        raise ValueError("Configure lsp.command as an argv list")
    process = subprocess.Popen(
        command,
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    inbox: queue.Queue = queue.Queue()

    def reader():
        try:
            while True:
                headers = {}
                while True:
                    raw = process.stdout.readline()
                    if not raw:
                        raise EOFError("Language server closed stdout")
                    if raw in (b"\r\n", b"\n"):
                        break
                    key, value = raw.decode("ascii").split(":", 1)
                    headers[key.lower()] = value.strip()
                length = int(headers["content-length"])
                if length < 0 or length > 8_000_000:
                    raise ValueError("LSP response exceeds size limit")
                inbox.put(json.loads(process.stdout.read(length)))
        except Exception as exc:
            inbox.put(exc)

    def send(message):
        data = json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8")
        process.stdin.write(
            f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data
        )
        process.stdin.flush()

    def receive(identifier):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Language server timed out")
            try:
                message = inbox.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError("Language server timed out") from exc
            if isinstance(message, Exception):
                raise RuntimeError(str(message))
            if "method" in message and "id" in message:
                # Reply to server requests rather than deadlocking initialization.
                if message["method"] == "workspace/configuration":
                    result = [None for _ in message.get("params", {}).get("items", [])]
                else:
                    result = None
                send({"id": message["id"], "result": result})
            elif message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(f"LSP: {message['error']}")
                return message.get("result")

    worker = threading.Thread(target=reader, daemon=True)
    worker.start()
    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": root.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
                },
            }
        )
        receive(1)
        send({"method": "initialized", "params": {}})
        send(
            {
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": path.as_uri(),
                        "languageId": language_id(path),
                        "version": 1,
                        "text": read_text(path),
                    }
                },
            }
        )
        params = {"textDocument": {"uri": path.as_uri()}}
        if operation not in {"symbols", "diagnostics"}:
            params["position"] = {
                "line": max(0, line - 1),
                "character": max(0, character - 1),
            }
        if operation == "references":
            params["context"] = {"includeDeclaration": True}
        send({"id": 2, "method": methods[operation], "params": params})
        result = receive(2)
        send({"id": 3, "method": "shutdown", "params": None})
        receive(3)
        send({"method": "exit", "params": None})
        return result
    finally:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        worker.join(timeout=1)
        process.stdin.close()
        process.stdout.close()
