from __future__ import annotations

import json
from pathlib import Path

from . import extensions, external, lsp, search, workspace
from .capabilities import Capability, CapabilityRegistry
from .code_intelligence import CodeIntelligenceService
from .execution import BackgroundSpec, CommandSpec, LocalExecutionBackend
from .memory import Session
from .mcp import MCPManager
from .permissions import ActionRequest, Permissions, parse_command
from .repo import files, read_text, safe_path
from . import skills
from .turns import SessionRuntime
from .tool_catalog import Exposure, ToolCatalog, ToolDescriptor


def schema(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


S = {"type": "string"}
INTEGER = {"type": "integer"}
BOOLEAN = {"type": "boolean"}
DEFINITIONS = [
    schema(
        "read",
        "Read UTF-8 file with line numbers (1-based).",
        {"path": S, "start": INTEGER, "end": INTEGER},
        ["path"],
    ),
    schema(
        "glob",
        "List project files, excluding generated and secret files.",
        {"pattern": S},
    ),
    schema(
        "grep",
        "Literal text search, optionally restricted by file glob.",
        {"query": S, "pattern": S},
        ["query"],
    ),
    schema(
        "write",
        "Create a UTF-8 file; use patch for existing files.",
        {"path": S, "content": S},
        ["path", "content"],
    ),
    schema(
        "patch",
        "Replace one exact, unique text block in an existing UTF-8 file. Validates before writing.",
        {"path": S, "old": S, "new": S},
        ["path", "old", "new"],
    ),
    schema(
        "terminal",
        "Execute a noninteractive shell command in the project. Set background only for a long-running local service; it returns PID and log path. Shell policy applies.",
        {"command": S, "cwd": S, "background": BOOLEAN},
        ["command"],
    ),
    schema(
        "test",
        "Run tests/lint/typecheck; record real exit code and output as validation evidence.",
        {
            "command": S,
            "cwd": S,
            "stage": {
                "type": "string",
                "enum": [
                    "reproduction",
                    "syntax",
                    "lint",
                    "typecheck",
                    "targeted",
                    "module",
                    "regression",
                    "integration",
                ],
            },
        },
        ["command"],
    ),
    schema(
        "git",
        "Read-only git operation. Never commits or pushes.",
        {
            "operation": {"type": "string", "enum": ["status", "diff", "log", "blame"]},
            "path": S,
        },
        ["operation"],
    ),
    schema(
        "bm25",
        "Rank text files for a natural-language/code query.",
        {"query": S},
        ["query"],
    ),
    schema(
        "ast",
        "Find declarations in supported source languages. Python uses a real AST; other languages use syntax-aware text matching and mark approximate results.",
        {"query": S},
    ),
    schema(
        "graph",
        "Find indexed source symbols that call a matching symbol. Static call edges are approximate outside Python.",
        {"query": S},
        ["query"],
    ),
    schema(
        "lsp",
        "Query a configured stdio language server (1-based line/character).",
        {
            "path": S,
            "operation": {
                "type": "string",
                "enum": ["definition", "references", "symbols", "hover", "diagnostics"],
            },
            "line": INTEGER,
            "character": INTEGER,
        },
        ["path", "operation"],
    ),
    schema(
        "localize",
        "Rank observed per-symbol coverage counts with SBFL. Never invent coverage.",
        {
            "spectra": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"symbol": S, "failed": INTEGER, "passed": INTEGER},
                    "required": ["symbol", "failed", "passed"],
                },
            },
            "total_failed": INTEGER,
            "total_passed": INTEGER,
            "formula": {"type": "string", "enum": ["ochiai", "tarantula", "dstar"]},
        },
        ["spectra", "total_failed", "total_passed"],
    ),
    schema(
        "coverage",
        "Import coverage.py JSON with test contexts, and rank covered lines with Ochiai.",
        {
            "path": S,
            "failing_contexts": {"type": "array", "items": S},
            "passing_contexts": {"type": "array", "items": S},
        },
        ["path", "failing_contexts", "passing_contexts"],
    ),
    schema(
        "artifact",
        "Save a planning/report artifact in this run. Never use for state or executable files.",
        {
            "name": S,
            "content": S,
        },
        ["name", "content"],
    ),
    schema(
        "delegate",
        "Run a bounded specialist with fresh context; returns an artifact summary.",
        {
            "agent": S,
            "task": S,
        },
        ["agent", "task"],
    ),
    schema(
        "submit",
        "Finish with evidence. Changes require passing validation and review, or an explicit reason validation is unavailable.",
        {"summary": S, "validation_note": S},
        ["summary"],
    ),
    schema(
        "plan_update",
        "Update the mutable task plan. Plans provide context only; they never trigger execution automatically.",
        {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"text": S, "status": S},
                    "required": ["text", "status"],
                    "additionalProperties": False,
                },
            }
        },
        ["steps"],
    ),
    schema(
        "plan_propose",
        "Save the final implementation-ready proposed plan. Only available in Plan Mode; it never edits source files or starts implementation.",
        {
            "summary": S,
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": S,
                        "files": {"type": "array", "items": S},
                        "details": S,
                    },
                    "required": ["title", "files", "details"],
                    "additionalProperties": False,
                },
            },
            "validation": {"type": "array", "items": S},
            "open_questions": {"type": "array", "items": S},
        },
        ["summary", "steps", "validation", "open_questions"],
    ),
    schema(
        "user_question",
        "Ask the user a focused question when their decision is required. This pauses the current turn until they answer.",
        {"question": S, "options": {"type": "array", "items": S}},
        ["question", "options"],
    ),
    schema(
        "workspace_context",
        "Return workspace boundary facts only: current directory, enclosing worktree root, instruction-file chain, trust, and an optional shallow tree. It never classifies the project or suggests commands.",
    ),
    schema(
        "code_definition",
        "Find the definition at a source position. Uses a configured language server when available, otherwise a generic source fallback.",
        {"path": S, "line": INTEGER, "character": INTEGER},
        ["path"],
    ),
    schema(
        "code_references",
        "Find references at a source position. Uses a configured language server when available, otherwise a text fallback.",
        {"path": S, "line": INTEGER, "character": INTEGER},
        ["path"],
    ),
    schema(
        "code_symbols",
        "List source declarations, optionally filtering by text and path. Python uses AST; other source formats use a marked approximate fallback.",
        {"query": S, "path": S},
    ),
    schema(
        "code_structure",
        "Describe declarations and local structure of one source file.",
        {"path": S},
        ["path"],
    ),
    schema(
        "code_diagnostics",
        "Request diagnostics for one source file through its configured language server.",
        {"path": S},
        ["path"],
    ),
    schema(
        "skill.list", "List optional reusable guidance available to this workspace."
    ),
    schema(
        "skill.load",
        "Load one optional skill when its procedure would help.",
        {"name": S},
        ["name"],
    ),
    schema(
        "tool_search",
        "Discover deferred capabilities by a short description, then make matching tools available for later turns.",
        {"query": S},
        ["query"],
    ),
    schema(
        "web_search",
        "Search the public web for current documentation or research. This is a deferred network capability.",
        {"query": S},
        ["query"],
    ),
    schema(
        "web_fetch",
        "Fetch an http(s) page and return cleaned, bounded text. This is a deferred network capability.",
        {"url": S, "max_chars": INTEGER},
        ["url"],
    ),
    schema(
        "agent_spawn",
        "Start an optional child agent with fresh task context. The parent may continue before waiting for it.",
        {"role": S, "task": S},
        ["task"],
    ),
    schema(
        "agent_send",
        "Send additional task context to a running or completed child agent.",
        {"agent_id": S, "message": S},
        ["agent_id", "message"],
    ),
    schema(
        "agent_wait",
        "Wait for one or more child agents and collect their current results.",
        {"agent_ids": {"type": "array", "items": S}},
        ["agent_ids"],
    ),
    schema(
        "agent_resume",
        "Resume a completed child agent with optional additional context.",
        {"agent_id": S, "message": S},
        ["agent_id"],
    ),
    schema(
        "agent_close",
        "Close a child agent and discard future work from it.",
        {"agent_id": S},
        ["agent_id"],
    ),
    schema(
        "mcp_connect",
        "Connect a configured stdio MCP server from .agent/mcp.yaml and discover its deferred tools.",
        {"server": S},
        ["server"],
    ),
    schema(
        "mcp_disconnect",
        "Disconnect an MCP server and remove its discovered tools.",
        {"server": S},
        ["server"],
    ),
    schema("mcp_list_servers", "List currently connected MCP servers."),
]
READ_TOOLS = {
    "read",
    "glob",
    "grep",
    "git",
    "bm25",
    "ast",
    "graph",
    "lsp",
    "code_definition",
    "code_references",
    "code_symbols",
    "code_structure",
    "code_diagnostics",
    "tool_search",
    "localize",
    "coverage",
}
ROLE_TOOLS = {
    "engineer": {d["function"]["name"] for d in DEFINITIONS},
    "explorer": READ_TOOLS | {"artifact", "submit"},
    "architect": READ_TOOLS | {"artifact", "submit"},
    "reviewer": READ_TOOLS | {"artifact", "submit"},
}

# Public names are capability-oriented. Old short names remain executable only
# for trajectory compatibility; they are not exposed to the model.
PUBLIC_NAMES = {
    "read": "fs.read",
    "glob": "fs.glob",
    "grep": "search.grep",
    "write": "fs.write",
    "patch": "patch.apply",
    "terminal": "terminal.exec",
    "test": "test.run",
    "git": "git.read",
    "bm25": "search.bm25",
    "ast": "code.ast",
    "graph": "code.graph",
    "lsp": "code.lsp",
    "localize": "fault.localize",
    "coverage": "fault.coverage",
    "artifact": "artifact.save",
    "delegate": "subagent",
    "plan_update": "plan.update",
    "plan_propose": "plan.propose",
    "user_question": "user.question",
    "tool_search": "tool.search",
    "web_search": "web.search",
    "web_fetch": "web.fetch",
    "agent_spawn": "agent.spawn",
    "agent_send": "agent.send",
    "agent_wait": "agent.wait",
    "agent_resume": "agent.resume",
    "agent_close": "agent.close",
    "mcp_connect": "mcp.connect",
    "mcp_disconnect": "mcp.disconnect",
    "mcp_list_servers": "mcp.list_servers",
    "workspace_context": "workspace.context",
    "code_definition": "code.definition",
    "code_references": "code.references",
    "code_symbols": "code.symbols",
    "code_structure": "code.structure",
    "code_diagnostics": "code.diagnostics",
}
PRIVATE_NAMES = {public: internal for internal, public in PUBLIC_NAMES.items()}
PRIVATE_NAMES["workspace.inspect"] = "workspace_context"
MAIN_TOOLS = {name for name in ROLE_TOOLS["engineer"] if name != "delegate"}
HIDDEN_TOOLS = {"ast", "graph", "lsp"}
PLAN_TOOLS = {
    "read",
    "glob",
    "grep",
    "bm25",
    "git",
    "code_definition",
    "code_references",
    "code_symbols",
    "code_structure",
    "code_diagnostics",
    "skill.list",
    "skill.load",
    "tool_search",
    "user_question",
    "agent_spawn",
    "agent_send",
    "agent_wait",
    "agent_resume",
    "agent_close",
    "web_search",
    "web_fetch",
    "plan_propose",
    "workspace_context",
}
PLAN_MUTATIONS = {"write", "patch", "terminal", "test", "artifact", "submit"}


def _public_schema(definition):
    function = {**definition["function"]}
    function["name"] = PUBLIC_NAMES.get(function["name"], function["name"])
    return {**definition, "function": function}


def validate_value(value, spec, name):
    kind = spec.get("type")
    valid = {
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }
    if kind in valid and not valid[kind]:
        raise ValueError(f"{name} must be {kind}")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f"Invalid {name}: {value}")
    if kind == "object":
        props = spec.get("properties", {})
        for key in spec.get("required", []):
            if key not in value:
                raise ValueError(f"Missing {name}.{key}")
        for key, item in value.items():
            if key not in props and spec.get("additionalProperties") is False:
                raise ValueError(f"Unknown argument {key}")
            if key in props:
                validate_value(item, props[key], key)
    if kind == "array":
        for item in value:
            validate_value(item, spec["items"], name)


class ToolRegistry:
    def __init__(
        self,
        root: Path,
        session: Session,
        permissions: Permissions,
        config: dict,
        *,
        shell="auto",
        dry_run=False,
        emit=print,
    ):
        self.root, self.session, self.permissions, self.config = (
            root,
            session,
            permissions,
            config,
        )
        self.shell, self.dry_run, self.emit = shell, dry_run, emit
        self.delegate = None
        self.agent_manager = None
        self.workspace = workspace.context(root)
        if config["execution"]["backend"] != "local":
            raise ValueError("Only the local execution backend is installed")
        self.execution = LocalExecutionBackend()
        self.code = CodeIntelligenceService(root, config)
        self.catalog = ToolCatalog(
            [definition["function"]["name"] for definition in DEFINITIONS],
            HIDDEN_TOOLS,
        )
        self.extensions = {tool.name: tool for tool in extensions.discover(root)}
        self.mcp = MCPManager(root)
        for tool in self.extensions.values():
            self.catalog.register(
                ToolDescriptor(tool.name, "extension", Exposure(tool.exposure))
            )
        self.capabilities = CapabilityRegistry()
        for definition in DEFINITIONS:
            function = definition["function"]
            if function["name"] in HIDDEN_TOOLS:
                continue
            name = PUBLIC_NAMES.get(function["name"], function["name"])
            effects = ()
            if function["name"] in {"write", "patch"}:
                effects = ("workspace_write",)
            elif function["name"] in {
                "terminal",
                "test",
                "lsp",
                "code_definition",
                "code_references",
                "code_diagnostics",
            }:
                effects = ("process_execution",)
            self.capabilities.register(
                Capability(
                    name,
                    "tool",
                    function["description"],
                    "high" if effects else "low",
                    effects,
                )
            )
        for tool in self.extensions.values():
            self.capabilities.register(Capability(tool.name, "tool", tool.description))

    def _register_extension(self, tool) -> None:
        if tool.name in self.extensions:
            return
        self.extensions[tool.name] = tool
        self.catalog.register(
            ToolDescriptor(tool.name, "extension", Exposure(tool.exposure))
        )
        self.capabilities.register(Capability(tool.name, "tool", tool.description))

    def _lsp_command(self, path: str) -> list[str]:
        """Compatibility shim for old persisted `code.lsp` calls."""
        return self.code.configured_command(path)

    def _cwd(self, name: str | None) -> Path:
        if not name:
            return self.root
        candidate = Path(name).expanduser()
        boundary = self.workspace.roots[0]
        path = (
            candidate if candidate.is_absolute() else boundary / candidate
        ).resolve()
        if not path.is_relative_to(boundary):
            raise ValueError("cwd escapes the workspace root")
        if not path.is_dir():
            raise ValueError("cwd must be an existing directory")
        return path

    def schemas_for(self, role="build"):
        internal_role = {"build": "engineer", "explore": "explorer"}.get(role, role)
        if internal_role not in ROLE_TOOLS:
            raise PermissionError(f"Unknown tool profile: {role}")
        allowed = ROLE_TOOLS[internal_role]
        if (
            internal_role == "engineer"
            and self.session.data.get("collaboration_mode") == "PLAN"
        ):
            allowed = allowed & PLAN_TOOLS
        enabled = set(self.session.data.setdefault("enabled_tools", []))
        visible = self.catalog.visible(allowed, enabled)
        schemas = [
            _public_schema(d) for d in DEFINITIONS if d["function"]["name"] in visible
        ]
        if internal_role == "engineer":
            schemas.extend(
                schema(tool.name, tool.description, tool.parameters)
                for tool in self.extensions.values()
                if tool.exposure == "direct" or tool.name in enabled
            )
        return schemas

    def execute(self, name: str, arguments: dict, role="build") -> dict:
        try:
            name = PRIVATE_NAMES.get(name, name)
            internal_role = {"build": "engineer", "explore": "explorer"}.get(role, role)
            extension = self.extensions.get(name)
            if (
                internal_role == "engineer"
                and self.session.data.get("collaboration_mode") == "PLAN"
                and name in PLAN_MUTATIONS
            ):
                raise PermissionError(f"Tool {name} is unavailable in Plan Mode")
            if internal_role not in ROLE_TOOLS or (
                not extension and name not in ROLE_TOOLS[internal_role]
            ):
                raise PermissionError(f"Tool {name} is unavailable to {role}")
            definition = (
                {
                    "parameters": {
                        "type": "object",
                        "properties": extension.parameters,
                        "additionalProperties": False,
                    }
                }
                if extension
                else next(
                    d["function"] for d in DEFINITIONS if d["function"]["name"] == name
                )
            )
            validate_value(arguments, definition["parameters"], name)
            self.emit(
                f"  [{role}] {name}: {str(arguments.get('path', arguments.get('command', arguments.get('query', ''))))[:180]}"
            )
            action = "read"
            if extension:
                action = extension.action
            if name in {
                "grep",
                "glob",
                "bm25",
                "ast",
                "graph",
                "localize",
                "coverage",
                "code_symbols",
                "code_structure",
            }:
                action = "search"
            elif name == "git":
                action = "git_read"
            elif name in {"write", "patch"}:
                action = "workspace_write"
            elif name == "artifact":
                action = "artifact_write"
            elif name == "terminal":
                action = "process_execution"
            elif name == "test":
                action = "test_execution"
            elif name == "lsp":
                action = "lsp_execution"
            elif name in {"code_definition", "code_references", "code_diagnostics"}:
                if self.code.configured_command(arguments["path"]):
                    action = "lsp_execution"
            elif name == "workspace_context":
                action = "workspace_inspect"
            elif name in {"web_search", "web_fetch"}:
                action = "network"
            elif name == "mcp_connect":
                action = "process_execution"
            elif name.startswith("skill."):
                action = "skill_read"
            detail = str(arguments.get("command", arguments.get("path", name)))
            command = arguments.get("command")
            if name == "lsp":
                command = " ".join(self._lsp_command(arguments["path"]))
                detail = command
            elif name in {"code_definition", "code_references", "code_diagnostics"}:
                command = " ".join(self.code.configured_command(arguments["path"]))
                detail = command or detail
            elif name == "mcp_connect":
                command = " ".join(self.mcp.configured(arguments["server"]))
                detail = command
            if self.dry_run and name in {
                "write",
                "patch",
                "terminal",
                "test",
                "lsp",
                "code_definition",
                "code_references",
                "code_diagnostics",
            }:
                return {
                    "ok": True,
                    "dry_run": True,
                    "output": "Planned only; not executed",
                    "arguments": arguments,
                }
            decision = self.permissions.authorize(
                ActionRequest(
                    role,
                    PUBLIC_NAMES.get(name, name),
                    action,
                    detail,
                    command,
                    parse_command(command) or () if isinstance(command, str) else (),
                    (arguments["path"],)
                    if isinstance(arguments.get("path"), str)
                    else (),
                    network=name in {"web_search", "web_fetch"}
                    or bool(extension and extension.action == "network"),
                    reason=arguments.get("reason", ""),
                )
            )
            if decision.decision != "allow":
                raise PermissionError(f"Denied by permission policy: {decision.reason}")
            result = (
                extension.executor(arguments)
                if extension
                else self._execute(name, arguments, internal_role)
            )
            return (
                result
                if isinstance(result, dict) and "ok" in result
                else {"ok": True, "result": result}
            )
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}

    def _execute(self, name, a, role):
        if name == "read":
            path = safe_path(self.root, a["path"])
            if (
                path.name == ".env"
                or path.name.startswith(".env.")
                and path.name != ".env.example"
            ):
                raise PermissionError("Credential files must be managed by the user")
            start, end = a.get("start", 1), a.get("end", a.get("start", 1) + 199)
            if start < 1 or end < start or end - start > 1000:
                raise ValueError("Request 1-based lines, up to 1001 at a time")
            lines = read_text(path).splitlines()
            return {
                "path": a["path"],
                "instructions": workspace.instructions(self.workspace),
                "text": "\n".join(
                    f"{i + 1}: {line}"
                    for i, line in enumerate(lines)
                    if start <= i + 1 <= end
                ),
            }
        if name == "glob":
            return [
                p.relative_to(self.root).as_posix()
                for p in files(self.root, a.get("pattern", "*"), 500)
            ]
        if name == "grep":
            hits = []
            for path in files(self.root, a.get("pattern", "*")):
                try:
                    for i, line in enumerate(read_text(path).splitlines(), 1):
                        if a["query"].lower() in line.lower():
                            hits.append(
                                {
                                    "path": path.relative_to(self.root).as_posix(),
                                    "line": i,
                                    "text": line[:500],
                                }
                            )
                            if len(hits) >= 100:
                                return hits
                except (OSError, ValueError):
                    continue
            return hits
        if name in {"write", "patch"}:
            path = safe_path(self.root, a["path"])
            if (
                path.name == ".env"
                or path.name.startswith(".env.")
                and path.name != ".env.example"
            ):
                raise PermissionError("Credential files must be managed by the user")
            if name == "write":
                if path.exists():
                    raise ValueError("File already exists; inspect it and use patch")
                data = a["content"].encode("utf-8")
            else:
                data = path.read_bytes()
                old = a["old"].encode("utf-8")
                new = a["new"].encode("utf-8")
                if b"\r\n" in data:
                    old = old.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                    new = new.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                if not old or data.count(old) != 1:
                    raise ValueError(
                        "Patch old text must match exactly once; no changes applied"
                    )
                data = data.replace(old, new, 1)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.session.data["edit_revision"] = (
                self.session.data.get("edit_revision", 0) + 1
            )
            return {"path": a["path"], "bytes": len(data)}
        if name in {"terminal", "test"}:
            if not a["command"].strip():
                raise ValueError("Command must not be empty")
            cwd = self._cwd(a.get("cwd"))
            if name == "terminal" and a.get("background"):
                log = (
                    self.session.directory
                    / "processes"
                    / f"terminal-{self.session.data['turn']}.log"
                )
                result = self.execution.start(
                    BackgroundSpec(a["command"], cwd, self.shell, log)
                )
                self.session.data.setdefault("background_processes", []).append(result)
            else:
                result = self.execution.execute(
                    CommandSpec(
                        a["command"],
                        cwd,
                        self.config["agent"]["command_timeout"],
                        self.shell,
                    )
                )
            if name == "test":
                self.session.data["validation"].append(
                    {
                        "command": a["command"],
                        "cwd": str(cwd.relative_to(self.workspace.roots[0])),
                        "stage": a.get("stage", "targeted"),
                        "turn": self.session.data["turn"],
                        "revision": self.session.data.get("edit_revision", 0),
                        **result,
                    }
                )
                self.session.artifact(
                    "validation.md",
                    json.dumps(
                        self.session.data["validation"], ensure_ascii=False, indent=2
                    ),
                )
            else:
                # Arbitrary shell may edit files, so invalidate earlier validation.
                self.session.data["edit_revision"] = (
                    self.session.data.get("edit_revision", 0) + 1
                )
            return result
        if name == "git":
            operation = a["operation"]
            args = {
                "status": ["status", "--short"],
                "diff": ["diff", "--no-ext-diff", "--no-textconv"],
                "log": ["log", "-5", "--oneline"],
                "blame": ["blame"],
            }[operation]
            if a.get("path"):
                path = safe_path(self.root, a["path"])
                args += ["--", path.relative_to(self.root).as_posix()]
            elif operation == "blame":
                raise ValueError("blame requires path")
            return self.execution.execute(
                CommandSpec(["git", "--no-pager", *args], self.root, 30)
            )
        if name == "bm25":
            return search.bm25(self.root, a["query"])
        if name in {"ast", "graph"}:
            symbols = search.symbols(
                self.root, a.get("query", "") if name == "ast" else ""
            )
            return (
                symbols
                if name == "ast"
                else [
                    s
                    for s in symbols
                    if any(a["query"].lower() in c.lower() for c in s["calls"])
                ]
            )
        if name == "code_definition":
            return self.code.definition(
                a["path"], a.get("line", 1), a.get("character", 1)
            )
        if name == "code_references":
            return self.code.references(
                a["path"], a.get("line", 1), a.get("character", 1)
            )
        if name == "code_symbols":
            return self.code.symbols(a.get("query", ""), a.get("path"))
        if name == "code_structure":
            return self.code.structure(a["path"])
        if name == "code_diagnostics":
            return self.code.diagnostics(a["path"])
        if name == "localize":
            result = search.localize(**a)
            self.session.artifact("localization.yaml", json.dumps(result, indent=2))
            return result
        if name == "coverage":
            report = json.loads(read_text(safe_path(self.root, a["path"])))
            spectra = search.coverage_spectra(
                report, a["failing_contexts"], a["passing_contexts"]
            )
            result = search.localize(**spectra)
            self.session.artifact("localization.yaml", json.dumps(result, indent=2))
            return result
        if name == "lsp":
            path = safe_path(self.root, a["path"])
            return lsp.query(
                self.root,
                path,
                self._lsp_command(a["path"]),
                a["operation"],
                a.get("line", 1),
                a.get("character", 1),
            )
        if name == "artifact":
            self.session.artifact(a["name"], a["content"])
            return f"Saved {a['name']}"
        if name == "workspace_context":
            return self.workspace.facts()
        if name == "skill.list":
            return [
                {"name": skill.name, "description": skill.description}
                for skill in skills.discover(self.root).values()
            ]
        if name == "skill.load":
            return skills.load(self.root, a["name"])
        if name == "tool_search":
            found = self.catalog.search(a["query"])
            enabled = set(self.session.data.setdefault("enabled_tools", []))
            enabled.update(item.name for item in found)
            self.session.data["enabled_tools"] = sorted(enabled)
            return [
                {
                    "name": PUBLIC_NAMES.get(item.name, item.name),
                    "category": item.category,
                    "exposure": item.exposure,
                }
                for item in found
            ]
        if name == "web_search":
            return external.search(a["query"])
        if name == "web_fetch":
            return external.fetch(a["url"], a.get("max_chars", 16_000))
        if name == "mcp_connect":
            tools = self.mcp.connect(a["server"])
            for tool in tools:
                self._register_extension(tool)
            enabled = set(self.session.data.setdefault("enabled_tools", []))
            enabled.update(tool.name for tool in tools)
            self.session.data["enabled_tools"] = sorted(enabled)
            return {"server": a["server"], "tools": [tool.name for tool in tools]}
        if name == "mcp_disconnect":
            prefix = "mcp." + a["server"] + "."
            self.mcp.disconnect(a["server"])
            for tool_name in [
                name for name in self.extensions if name.startswith(prefix)
            ]:
                self.extensions.pop(tool_name)
                self.catalog.unregister(tool_name)
            self.session.data["enabled_tools"] = [
                tool_name
                for tool_name in self.session.data.get("enabled_tools", [])
                if not tool_name.startswith(prefix)
            ]
            return {"server": a["server"], "disconnected": True}
        if name == "mcp_list_servers":
            return self.mcp.list_servers()
        if name.startswith("agent_"):
            if not self.agent_manager:
                raise RuntimeError("Agent manager is unavailable in this context")
            if name == "agent_spawn":
                return self.agent_manager.public(
                    self.agent_manager.spawn(a.get("role", "general"), a["task"])
                )
            if name == "agent_send":
                self.agent_manager.send(a["agent_id"], a["message"])
                return {"agent_id": a["agent_id"], "sent": True}
            if name == "agent_wait":
                return self.agent_manager.wait(a["agent_ids"])
            if name == "agent_resume":
                return self.agent_manager.public(
                    self.agent_manager.resume(a["agent_id"], a.get("message", ""))
                )
            self.agent_manager.close(a["agent_id"])
            return {"agent_id": a["agent_id"], "closed": True}
        if name in {"delegate", "subagent"}:
            if not self.delegate:
                raise RuntimeError("Delegation is unavailable in this context")
            return self.delegate(a.get("agent", a.get("role")), a["task"])
        if name == "submit":
            return {
                "summary": a["summary"],
                "validation_note": a.get("validation_note", ""),
            }
        if name == "plan_update":
            return {"steps": SessionRuntime(self.session).update_plan(a["steps"])}
        if name == "plan_propose":
            return {"proposed_plan": SessionRuntime(self.session).propose(a)}
        if name == "user_question":
            return {
                "blocked": True,
                **SessionRuntime(self.session).question(a["question"], a["options"]),
            }
        raise ValueError(f"Unknown tool {name}")
