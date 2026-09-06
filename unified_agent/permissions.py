"""Capability-based authorization for local tool execution.

This is an authorization harness, not an operating-system sandbox. In
particular, allowing a process to run gives it the user's OS privileges.
"""

from __future__ import annotations

import re
import shlex
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

Decision = Literal["allow", "prompt", "deny"]
Approval = Literal["once", "session", "deny"]

HARD_DENY_PREFIXES = {
    ("sudo",),
    ("doas",),
    ("mkfs",),
    ("shutdown",),
    ("reboot",),
    ("poweroff",),
    ("halt",),
    ("diskpart",),
    ("format",),
}
COMPOUND_SHELL = re.compile(r"(?:[\r\n;&|`<>]|\$\(|\$\{|\x00)")


@dataclass(frozen=True)
class ActionRequest:
    agent: str
    tool: str
    action: str
    resource: str = ""
    command: str | None = None
    argv: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    network: bool = False
    reason: str = ""


@dataclass(frozen=True)
class PermissionDecision:
    decision: Decision
    reason: str
    source: str
    matched_rule: str | None = None


@dataclass(frozen=True)
class PrefixRule:
    pattern: tuple[str, ...]
    decision: Decision
    reason: str = ""
    source: str = "project_rule"

    def matches(self, argv: tuple[str, ...]) -> bool:
        return len(argv) >= len(self.pattern) and all(
            expected == "*" or expected == actual
            for expected, actual in zip(self.pattern, argv)
        )


def parse_command(command: str) -> tuple[str, ...] | None:
    """Parse one simple command; compound shell syntax deliberately has no allow rule."""
    if not command.strip() or COMPOUND_SHELL.search(command):
        return None
    try:
        # posix=False retains Windows paths and quotes well enough for prefix policy.
        argv = tuple(shlex.split(command, posix=False))
    except ValueError:
        return None
    return argv or None


def _rules(data: dict[str, Any], source: str) -> list[PrefixRule]:
    rows = data.get("rules", [])
    if not isinstance(rows, list):
        raise ValueError("Permission rules must be a list")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Permission rule must be a mapping")
        pattern, decision = row.get("pattern"), row.get("decision", row.get("effect"))
        if (
            not isinstance(pattern, list)
            or not pattern
            or not all(isinstance(item, str) and item for item in pattern)
        ):
            raise ValueError("Rule pattern must be a nonempty argv list")
        if decision not in {"allow", "prompt", "deny"}:
            raise ValueError("Rule decision must be allow, prompt, or deny")
        result.append(
            PrefixRule(tuple(pattern), decision, str(row.get("reason", "")), source)
        )
    # Read the predecessor format only for migration. It is normalized into
    # argv prefix rules before evaluation; no raw-string matching remains.
    legacy = data.get("shell_rules", {})
    if legacy:
        if not isinstance(legacy, dict):
            raise ValueError("shell_rules must be a mapping")
        for decision in ("allow", "ask", "deny"):
            for command in legacy.get(decision, []):
                argv = parse_command(command)
                if argv:
                    result.append(
                        PrefixRule(
                            argv,
                            "prompt" if decision == "ask" else decision,
                            "Migrated legacy command rule",
                            source,
                        )
                    )
    return result


class PermissionAudit:
    def __init__(self, root: Path):
        self.path = root / ".agent" / "permissions.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS permission_events (
                id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, session_id TEXT,
                agent TEXT NOT NULL, tool TEXT NOT NULL, action TEXT NOT NULL,
                resource TEXT NOT NULL, command TEXT, decision TEXT NOT NULL,
                source TEXT NOT NULL, reason TEXT NOT NULL, matched_rule TEXT)""")
            db.commit()

    def record(
        self,
        session_id: str | None,
        request: ActionRequest,
        decision: PermissionDecision,
    ):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(
                "INSERT INTO permission_events(timestamp,session_id,agent,tool,action,resource,command,decision,source,reason,matched_rule) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                    request.agent,
                    request.tool,
                    request.action,
                    request.resource,
                    request.command,
                    decision.decision,
                    decision.source,
                    decision.reason,
                    decision.matched_rule,
                ),
            )
            db.commit()


class Permissions:
    """Access profile + approval policy + argv prefix rules + session grants."""

    def __init__(
        self,
        config: dict | None = None,
        confirm: Callable[[ActionRequest, PermissionDecision], Approval] | None = None,
        *,
        root: Path | None = None,
        session_id: str | None = None,
        user_rules: dict | None = None,
    ):
        self.config = config or {}
        self.confirm = confirm
        self.session_id = session_id
        self.profile = self.config.get("access_profile", "workspace")
        self.approval_policy = self.config.get("approval_policy", "on-request")
        if self.profile not in {"inspect", "workspace", "full"}:
            raise ValueError("access_profile must be inspect, workspace, or full")
        if self.approval_policy not in {"on-request", "never"}:
            raise ValueError("approval_policy must be on-request or never")
        self.rules = _rules(user_rules or {}, "user_rule") + _rules(
            self.config, "project_rule"
        )
        self.session_grants: list[tuple[str, tuple[str, ...]]] = []
        self.audit = PermissionAudit(root) if root else None

    def _profile_decision(self, request: ActionRequest) -> PermissionDecision | None:
        if request.action in {
            "read",
            "search",
            "workspace_inspect",
            "git_read",
            "skill_read",
        }:
            return PermissionDecision(
                "allow", "Read-only workspace capability", "access_profile"
            )
        if self.profile == "inspect":
            return PermissionDecision(
                "prompt",
                "Inspect profile requires approval for changes or process execution",
                "access_profile",
            )
        if self.profile == "workspace" and request.action in {
            "workspace_write",
            "artifact_write",
        }:
            return PermissionDecision(
                "allow",
                "Workspace profile permits project file changes",
                "access_profile",
            )
        return None

    @staticmethod
    def _dangerous(argv: tuple[str, ...]) -> bool:
        lower = tuple(part.lower() for part in argv)
        if any(lower[: len(prefix)] == prefix for prefix in HARD_DENY_PREFIXES):
            return True
        if lower[:2] == ("git", "push") and any(
            item in {"--force", "-f"} for item in lower[2:]
        ):
            return True
        return lower[:2] in {("rm", "-rf"), ("rm", "-fr"), ("remove-item", "-recurse")}

    def _shell_decision(self, request: ActionRequest) -> PermissionDecision:
        argv = request.argv
        if self.profile == "full":
            return PermissionDecision(
                "allow",
                "Full profile permits unrestricted local command execution",
                "access_profile",
            )
        if not argv:
            return PermissionDecision(
                "prompt",
                "Compound or unparsable shell command requires explicit approval",
                "exec_policy",
            )
        if self._dangerous(argv):
            return PermissionDecision(
                "deny",
                "Dangerous command denied by the built-in safety baseline",
                "hard_deny",
            )
        grants = [
            prefix
            for action, prefix in self.session_grants
            if action == request.action and argv[: len(prefix)] == prefix
        ]
        if grants:
            return PermissionDecision(
                "allow",
                "Approved for this session",
                "session_grant",
                " ".join(max(grants, key=len)),
            )
        matches = [rule for rule in self.rules if rule.matches(argv)]
        if matches:
            size = max(len(rule.pattern) for rule in matches)
            candidates = [rule for rule in matches if len(rule.pattern) == size]
            rule = min(
                candidates,
                key=lambda item: {"deny": 0, "prompt": 1, "allow": 2}[item.decision],
            )
            return PermissionDecision(
                rule.decision,
                rule.reason or "Matched command rule",
                rule.source,
                " ".join(rule.pattern),
            )
        if self.config.get("shell", {}).get("default") == "allow":
            return PermissionDecision(
                "allow", "Migrated legacy shell default", "legacy_config"
            )
        return PermissionDecision(
            "allow" if self.profile == "full" else "prompt",
            "No matching command rule",
            "default_policy",
        )

    def evaluate(self, request: ActionRequest) -> PermissionDecision:
        if request.action in {"process_execution", "test_execution", "lsp_execution"}:
            decision = self._shell_decision(request)
        else:
            decision = self._profile_decision(request) or PermissionDecision(
                "allow", "Tool has no additional side effect", "tool_metadata"
            )
        if self.approval_policy == "never" and decision.decision == "prompt":
            decision = PermissionDecision(
                "deny",
                "Approval policy is never; prompted action was not executed",
                "approval_policy",
                decision.matched_rule,
            )
        if self.audit:
            self.audit.record(self.session_id, request, decision)
        return decision

    def authorize(self, request: ActionRequest) -> PermissionDecision:
        decision = self.evaluate(request)
        if decision.decision != "prompt":
            return decision
        answer: Approval = self.confirm(request, decision) if self.confirm else "deny"
        if answer == "session" and request.argv:
            self.session_grants.append(
                (
                    request.action,
                    request.argv[:2] if len(request.argv) > 1 else request.argv,
                )
            )
            final = PermissionDecision(
                "allow",
                "User approved matching command for this session",
                "user_session_grant",
            )
        elif answer == "once":
            final = PermissionDecision(
                "allow", "User approved this action once", "user_once"
            )
        else:
            final = PermissionDecision("deny", "User denied approval", "user")
        if self.audit:
            self.audit.record(self.session_id, request, final)
        return final

    # Compatibility helpers for extensions written against the early MVP.
    def decision(self, category: str, detail: str) -> str:
        action = "process_execution" if category == "shell" else category
        request = ActionRequest(
            "main", "compat", action, detail, detail, parse_command(detail) or ()
        )
        return self.evaluate(request).decision

    def check(self, category: str, detail: str) -> None:
        action = "process_execution" if category == "shell" else category
        decision = self.authorize(
            ActionRequest(
                "main", "compat", action, detail, detail, parse_command(detail) or ()
            )
        )
        if decision.decision != "allow":
            raise PermissionError(f"Denied by permission policy: {decision.reason}")
