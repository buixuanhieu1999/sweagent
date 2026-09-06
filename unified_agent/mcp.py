"""Minimal stdio MCP client for configured, discoverable external tools."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import load_mapping
from .extensions import ExtensionTool


@dataclass
class MCPServer:
    name: str
    process: subprocess.Popen
    next_id: int = 1

    def call(self, method: str, params: dict | None = None):
        identifier = self.next_id
        self.next_id += 1
        payload = {"jsonrpc": "2.0", "id": identifier, "method": method}
        if params is not None:
            payload["params"] = params
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP server {self.name} closed stdout")
            message = json.loads(line)
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError("MCP: " + json.dumps(message["error"]))
                return message.get("result")


class MCPManager:
    def __init__(self, root: Path):
        self.root = root
        self.servers: dict[str, MCPServer] = {}

    def configured(self, name: str) -> list[str]:
        data = load_mapping(self.root / ".agent" / "mcp.yaml")
        servers = data.get("servers", {})
        entry = servers.get(name) if isinstance(servers, dict) else None
        command = entry.get("command") if isinstance(entry, dict) else None
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) for part in command)
        ):
            raise ValueError(f"MCP server {name!r} needs servers.{name}.command argv")
        return command

    def connect(self, name: str) -> list[ExtensionTool]:
        if name in self.servers:
            return self.tools(name)
        process = subprocess.Popen(
            self.configured(name),
            cwd=self.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        server = MCPServer(name, process)
        server.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "unified-agent", "version": "0.1"},
            },
        )
        self.servers[name] = server
        return self.tools(name)

    def tools(self, name: str) -> list[ExtensionTool]:
        if name not in self.servers:
            raise ValueError(f"MCP server {name} is not connected")
        server = self.servers[name]
        rows = server.call("tools/list").get("tools", [])
        result = []
        for row in rows:
            tool_name = row.get("name")
            if not isinstance(tool_name, str):
                continue
            schema = row.get("inputSchema", {})
            parameters = (
                schema.get("properties", {}) if isinstance(schema, dict) else {}
            )
            result.append(
                ExtensionTool(
                    f"mcp.{name}.{tool_name}",
                    str(row.get("description", "MCP tool")),
                    parameters if isinstance(parameters, dict) else {},
                    lambda arguments, server=server, tool_name=tool_name: server.call(
                        "tools/call", {"name": tool_name, "arguments": arguments}
                    ),
                    action="network",
                )
            )
        return result

    def disconnect(self, name: str) -> None:
        server = self.servers.pop(name, None)
        if not server:
            return
        server.process.terminate()
        try:
            server.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            server.process.kill()
            server.process.wait()
        if server.process.stdin:
            server.process.stdin.close()
        if server.process.stdout:
            server.process.stdout.close()

    def list_servers(self) -> list[str]:
        return sorted(self.servers)
