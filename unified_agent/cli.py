from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path

from .config import load_config, load_mapping
from .legacy import load_dotenv
from .memory import Session, diff_snapshots, experiences, snapshot
from .permissions import ActionRequest, PermissionDecision, Permissions
from .provider import OllamaProvider
from .repo import safe_path
from .runtime import MainAgent
from .tools import ToolRegistry
from .turns import SessionRuntime, TurnState

HELP = """Type a natural-language request to explore, repair or build a project.
/help                 Show this help
/status               Show session state, validation and request count
/diff                 Show this session's changes (including new files)
/test [command]       Run configured checks, or an explicit test command
/review               Review the current changes
/plan                 Show the mutable plan for the active session
/queue <request>      Queue a follow-up to run after the current turn
/interrupt            Mark the active turn interrupted; Ctrl+C also interrupts running work
/compact              Summarize old context, preserving recent tool exchanges
/memory [lesson]      Retrieve experience, or save an explicit lesson
/model [name]         Show/change the main model for this session
/permissions          Show the effective policy
/undo, /redo          Restore the previous/next recorded file change
/clear                Start a fresh conversation in a new saved session
/exit                 Save and exit
Ctrl+C interrupts work; type 'continue' or 'tiếp tục' to continue.
"""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Unified interactive local coding agent (Ollama)"
    )
    parser.add_argument(
        "--task",
        "-t",
        help="Optional one-shot task; otherwise start an interactive session",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--model")
    parser.add_argument("--host", help="Ollama host with or without /api")
    parser.add_argument("--api-key", help="Explicit key for the chosen endpoint")
    parser.add_argument(
        "--max-agent-turns",
        type=int,
        help="Optional model-request cap for evaluation or a fixed budget; unlimited by default",
    )
    # Keep old invocation scripts working without retaining it as the public name.
    parser.add_argument(
        "--max-steps", type=int, dest="max_agent_turns", help=argparse.SUPPRESS
    )
    parser.add_argument("--command-timeout", type=int)
    parser.add_argument(
        "--shell", choices=("auto", "bash", "powershell", "cmd"), default="auto"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--full-access",
        action="store_true",
        help="Allow all local agent tool calls and commands without permission prompts",
    )
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument(
        "--resume",
        nargs="?",
        const="latest",
        help="Resume a saved session ID, or latest",
    )
    parser.add_argument(
        "--new-session", action="store_true", help="Skip unfinished-session detection"
    )
    parser.add_argument(
        "--output", help="Also export a portable trajectory JSON after each turn"
    )
    args = parser.parse_args(argv)
    for key in ("max_agent_turns", "command_timeout"):
        if getattr(args, key) is not None and getattr(args, key) < 1:
            parser.error(f"--{key.replace('_', '-')} must be positive")
    if args.resume and args.new_session:
        parser.error("--resume and --new-session are mutually exclusive")
    return args


def confirm(request: ActionRequest, decision: PermissionDecision) -> str:
    if not sys.stdin.isatty():
        return "deny"
    try:
        print("\nPermission required")
        print(f"Agent: {request.agent}\nTool: {request.tool}\nAction: {request.action}")
        if request.command:
            print(f"Command: {request.command}")
        if request.paths:
            print("Paths: " + ", ".join(request.paths))
        print(f"Workspace: {request.resource or 'current workspace'}")
        print(f"Reason: {request.reason or decision.reason}")
        answer = input(
            "[1] Allow once  [2] Allow matching command this session  [3] Deny (default): "
        ).strip()
        return {"1": "once", "2": "session"}.get(answer, "deny")
    except EOFError:
        return "deny"


def confirm_resume(run_id: str) -> bool:
    """Ask about session lifecycle without reusing the permission callback."""
    if not sys.stdin.isatty():
        return False
    try:
        return input(
            f"Resume unfinished session {run_id}? [y/N]: "
        ).strip().lower() in {
            "y",
            "yes",
        }
    except EOFError:
        return False


def command(text, agent: MainAgent):
    name, _, arg = text.partition(" ")
    arg = arg.strip()
    data = agent.session.data
    if name == "/help":
        print(HELP)
    elif name == "/status":
        print(
            json.dumps(
                {
                    k: data.get(k)
                    for k in (
                        "run_id",
                        "state",
                        "verification",
                        "model_requests",
                        "plan",
                        "runtime",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif name == "/diff":
        print(data.get("last_diff") or "No recorded file changes in this session.")
    elif name == "/test":
        checks = {"targeted": arg} if arg else agent.config["validation"]
        if not checks:
            print(
                "No validation commands configured. Use /test <command> or .agent/config.yaml."
            )
        for stage, test_command in checks.items():
            print(
                json.dumps(
                    agent.tools.execute(
                        "test", {"command": test_command, "stage": stage}
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    elif name == "/review":
        agent.run(
            "Review the current project changes. Latest recorded diff:\n"
            + data.get("last_diff", "")
        )
    elif name == "/plan":
        print(json.dumps(data.get("plan", []), ensure_ascii=False, indent=2))
    elif name == "/queue":
        SessionRuntime(agent.session).enqueue(arg)
        print("Follow-up queued.")
    elif name == "/interrupt":
        SessionRuntime(agent.session).state(TurnState.INTERRUPTED)
        data["state"] = "INTERRUPTED"
        print("Turn marked interrupted. Describe how to continue when ready.")
    elif name == "/compact":
        agent.calls = 0
        print(agent.compact())
    elif name == "/memory":
        if arg:
            path = agent.session.root / ".agent" / "memory" / "experience.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"lesson": arg, "run_id": agent.session.run_id},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            print("Lesson saved.")
        else:
            print(
                json.dumps(
                    experiences(agent.session.root, " ".join(data["requests"])),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    elif name == "/model":
        if arg:
            agent.provider.model = arg
            agent.config["models"]["engineer"] = arg
            data["model"] = arg
        print("Model: " + agent.provider.model)
    elif name == "/permissions":
        print("Authorization policy (not an OS sandbox):")
        print(
            json.dumps(
                {
                    "access_profile": agent.tools.permissions.profile,
                    "approval_policy": agent.tools.permissions.approval_policy,
                    "rules": [
                        " ".join(rule.pattern) + " → " + rule.decision
                        for rule in agent.tools.permissions.rules
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif name in {"/undo", "/redo"}:
        if agent.tools.dry_run:
            print("Dry run: history was not applied.")
        else:
            agent.tools.permissions.check("edit", name)
            print(agent.history.move(name == "/redo"))
            data["edit_revision"] = data.get("edit_revision", 0) + 1
            data["last_diff"] = diff_snapshots(
                data.get("session_baseline", {}), snapshot(agent.session.root)
            )
            agent.session.artifact("patch.diff", data["last_diff"])
            data["messages"].append(
                {
                    "role": "user",
                    "content": f"User applied {name}. Re-inspect the files before making changes.",
                }
            )
    elif name == "/clear":
        return "clear"
    elif name == "/exit":
        return "exit"
    else:
        print(
            f"Unknown session command: {name}. Use /help, or describe your task naturally."
        )
    agent.session.save()
    return "continue"


def main(argv=None) -> int:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    args = parse_args(argv)
    root = Path(args.repo).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(
            f"Project directory does not exist: {root}. Create it first for a new project."
        )
    config = load_config(root)
    settings = config["provider"]
    for key in ("model", "host"):
        if getattr(args, key):
            settings[key] = getattr(args, key)
    for key in ("max_agent_turns", "command_timeout"):
        if getattr(args, key):
            config["agent"][key] = getattr(args, key)
    for section, key in (
        ("agent", "command_timeout"),
        ("provider", "timeout"),
        ("compaction", "max_chars"),
        ("compaction", "recent_messages"),
    ):
        if type(config[section][key]) is not int or config[section][key] < 1:
            raise ValueError(f"{section}.{key} must be a positive integer")
    for key in ("max_agent_turns", "max_role_turns"):
        value = config["agent"][key]
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(f"agent.{key} must be a positive integer or null")
    if args.no_stream:
        settings["stream"] = False
    cloud = urllib.parse.urlsplit(settings["host"]).hostname == "ollama.com"
    key = args.api_key or (os.getenv("OLLAMA_API_KEY") if cloud else None)
    provider = OllamaProvider(
        settings["model"],
        settings["host"],
        key,
        settings["timeout"],
        settings["keep_alive"],
        settings.get("think"),
    )
    policy_path = safe_path(root, config["permissions"]["file"], internal=True)
    if not policy_path.exists():
        legacy_policy = root / ".agent" / "permissions.yaml"
        if legacy_policy.exists():
            policy_path = legacy_policy
    user_path = Path(config["permissions"]["user_file"]).expanduser()
    policy = {**config["permissions"], **load_mapping(policy_path)}
    if args.full_access:
        policy["access_profile"] = "full"
    run_id = args.resume
    if run_id == "latest":
        run_id = Session.latest(root)
        if run_id is None:
            raise ValueError("No saved session to resume")
    if not run_id and not args.new_session and not args.task:
        latest = Session.latest(root)
        if latest:
            state = json.loads(
                (root / ".agent" / "runs" / latest / "state.json").read_text(
                    encoding="utf-8"
                )
            )
            if state["state"] not in {"READY", "IDLE"} and confirm_resume(latest):
                run_id = latest

    def make_agent(identifier=None):
        session = Session(root, identifier)
        if identifier and session.data.get("model") and not args.model:
            provider.model = session.data["model"]
            config["models"]["engineer"] = provider.model
        permissions = Permissions(
            policy,
            confirm,
            root=root,
            session_id=session.run_id,
            user_rules=load_mapping(user_path),
        )
        registry = ToolRegistry(
            root, session, permissions, config, shell=args.shell, dry_run=args.dry_run
        )
        return MainAgent(provider, session, registry, config)

    agent = make_agent(run_id)
    print(
        f"Unified Coding Agent\nrepo: {root}\nprovider: Ollama\nmodel: {provider.model}\nendpoint: {provider.host}\nType /help for session commands."
    )
    if not provider.health():
        print(
            f"Ollama unavailable at {provider.host}. Start Ollama/check endpoint and authentication, then retry.",
            file=sys.stderr,
        )
        if args.task:
            return 2

    def export():
        if args.output:
            from .memory import atomic_json

            atomic_json(
                Path(args.output).expanduser().resolve(),
                {
                    "info": {
                        k: agent.session.data.get(k)
                        for k in ("state", "summary", "repo")
                    },
                    "messages": agent.session.data["messages"],
                },
            )

    if args.task:
        agent.run(args.task)
        export()
        return 0 if agent.session.data["state"] == "READY" else 1
    while True:
        try:
            text = input("\n> ").strip()
            if not text:
                continue
            if text.startswith("/"):
                action = command(text, agent)
                if action == "exit":
                    break
                if action == "clear":
                    agent = make_agent()
                    print("Started a new session; previous session remains saved.")
            else:
                agent.run(text)
                while agent.session.data["state"] == "READY":
                    follow_up = SessionRuntime(agent.session).next_queued()
                    if not follow_up:
                        break
                    print("[queued follow-up]")
                    agent.run(follow_up)
            export()
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\nInterrupted. Use /exit to leave.")
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
    agent.session.save()
    return 0


def entrypoint():
    try:
        return main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Agent error: {exc}", file=sys.stderr)
        return 1
