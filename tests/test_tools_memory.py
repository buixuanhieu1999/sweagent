import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from unified_agent.config import load_config
from unified_agent.memory import History, Session, compact, diff_snapshots, snapshot
from unified_agent.permissions import ActionRequest, Permissions
from unified_agent.provider import ProviderResponse
from unified_agent.repo import instructions
from unified_agent.search import bm25, localize, symbols
from unified_agent.terminal import execute, start
from unified_agent.tools import ToolRegistry


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.session = Session(self.root)
        self.tools = ToolRegistry(
            self.root,
            self.session,
            Permissions(),
            load_config(self.root),
            emit=lambda *a, **k: None,
        )

    def test_patch_is_exact_and_preserves_crlf(self):
        path = self.root / "code.py"
        path.write_bytes(b"x = 1\r\ny = 2\r\n")
        result = self.tools.execute(
            "patch", {"path": "code.py", "old": "x = 1\ny = 2", "new": "x = 3\ny = 2"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(path.read_bytes(), b"x = 3\r\ny = 2\r\n")
        result = self.tools.execute(
            "patch", {"path": "code.py", "old": "absent", "new": "oops"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(path.read_bytes(), b"x = 3\r\ny = 2\r\n")

    def test_diff_preserves_missing_newline_and_empty_file_creation(self):
        path = self.root / "x.py"
        path.write_bytes(b"old")
        before = snapshot(self.root)
        path.write_bytes(b"new")
        (self.root / "empty.py").touch()
        diff = diff_snapshots(before, snapshot(self.root))
        self.assertIn("-old\n\\ No newline at end of file\n+new\n", diff)
        self.assertIn("diff --git a/empty.py b/empty.py\nnew file mode 100644", diff)

    def test_paths_internals_and_secrets_are_protected(self):
        for path in ("../outside.txt", ".agent/state.json", ".git/config", ".env"):
            result = self.tools.execute("write", {"path": path, "content": "bad"})
            self.assertFalse(result["ok"], path)
        (self.root / ".env").write_text("secret")
        self.assertFalse(self.tools.execute("read", {"path": ".env"})["ok"])

    def test_dry_run_does_not_touch_files_or_spawn_processes(self):
        self.tools.dry_run = True
        for name, args in (
            ("write", {"path": "x.py", "content": "bad"}),
            ("terminal", {"command": "invalid"}),
            ("test", {"command": "invalid"}),
        ):
            self.assertTrue(self.tools.execute(name, args)["dry_run"])
        self.assertFalse((self.root / "x.py").exists())
        self.assertEqual(self.session.data["validation"], [])

    def test_validation_denied_in_noninteractive_mode(self):
        self.assertFalse(
            self.tools.execute("test", {"command": "python -m unittest"})["ok"]
        )

    def test_role_boundary_is_enforced_even_for_fabricated_calls(self):
        result = self.tools.execute(
            "write", {"path": "main.py", "content": "pass"}, "explorer"
        )
        self.assertFalse(result["ok"])
        result = self.tools.execute(
            "write", {"path": "main.py", "content": "pass"}, "reproducer"
        )
        self.assertFalse(result["ok"])

    def test_tool_schema_rejects_wrong_types_and_unknown_arguments(self):
        self.assertFalse(self.tools.execute("read", {"path": 7})["ok"])
        self.assertFalse(
            self.tools.execute("write", {"path": "x", "content": "x", "extra": 1})["ok"]
        )
        self.assertFalse((self.root / "x").exists())

    def test_scoped_instructions_and_search_skip_generated_directories(self):
        (self.root / "AGENTS.md").write_text("root instructions")
        (self.root / "src").mkdir()
        (self.root / "src" / "AGENTS.md").write_text("nested instructions")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "AGENTS.md").write_text("ignore")
        text = instructions(self.root)
        self.assertIn("root instructions", text)
        self.assertIn("Scope: src/", text)
        self.assertNotIn("ignore", text)

    def test_undo_redo_preserve_user_edits_and_survive_restart(self):
        path = self.root / "main.py"
        path.write_text("before\n")
        before = snapshot(self.root)
        path.write_text("after\n")
        history = History(self.session)
        history.record(before, snapshot(self.root))
        history = History(Session(self.root, self.session.run_id))
        history.move()
        self.assertEqual(path.read_text(), "before\n")
        history.move(redo=True)
        self.assertEqual(path.read_text(), "after\n")
        path.write_text("user change\n")
        with self.assertRaisesRegex(ValueError, "subsequent changes"):
            history.move()
        self.assertEqual(path.read_text(), "user change\n")

    def test_resume_closes_pending_tool_exchange_without_execution(self):
        self.session.data["messages"] = [
            {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "write", "arguments": {}}}],
            }
        ]
        self.session.save()
        resumed = Session(self.root, self.session.run_id)
        self.assertEqual(resumed.data["messages"][-1]["role"], "tool")
        self.assertIn("Outcome unknown", resumed.data["messages"][-1]["content"])

    def test_terminal_records_exit_and_timeout(self):
        result = execute([sys.executable, "-c", "print('test-output')"], self.root, 5)
        self.assertTrue(result["ok"])
        self.assertIn("test-output", result["output"])
        result = execute(
            [sys.executable, "-c", "import sys; sys.exit(7)"], self.root, 5
        )
        self.assertEqual(result["exit_code"], 7)
        result = execute(
            [sys.executable, "-c", "import time; time.sleep(30)"], self.root, 1
        )
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["ok"])

    def test_terminal_can_start_a_background_process_with_log(self):
        log = self.root / "background.log"
        process = Mock(pid=4321)
        with patch("unified_agent.terminal.subprocess.Popen", return_value=process):
            result = start(
                [sys.executable, "-c", "print('background-ready')"],
                self.root,
                log_path=log,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 4321)
        self.assertEqual(Path(result["log"]), log)

    def test_search_ranks_relevant_files_and_extracts_calls(self):
        (self.root / "auth.py").write_text(
            "def refresh_token():\n    return rotate_atomic()\n"
        )
        (self.root / "other.py").write_text("def weather():\n    return 5\n")
        self.assertEqual(bm25(self.root, "refresh token")[0]["path"], "auth.py")
        self.assertEqual(symbols(self.root, "refresh")[0]["calls"], ["rotate_atomic"])


class LogicTests(unittest.TestCase):
    def test_argv_prefix_rules_cannot_authorize_shell_chaining(self):
        policy = Permissions(
            {
                "rules": [
                    {"pattern": ["pytest"], "decision": "allow"},
                    {"pattern": ["git", "push"], "decision": "deny"},
                ]
            }
        )
        self.assertEqual(policy.decision("shell", "pytest tests"), "allow")
        for command in (
            "pytest tests; remove-file",
            "pytest $(danger)",
            "pytest tests\nother",
            "pytest tests > file",
        ):
            self.assertEqual(policy.decision("shell", command), "prompt")
        self.assertEqual(policy.decision("shell", "git push origin"), "deny")

    def test_permissions_profiles_grants_and_never_policy(self):
        answers = iter(["session"])
        request = ActionRequest(
            "build",
            "terminal.exec",
            "process_execution",
            command="npm install zod",
            argv=("npm", "install", "zod"),
        )
        policy = Permissions(
            {"access_profile": "workspace", "approval_policy": "on-request"},
            lambda *_: next(answers),
        )
        self.assertEqual(policy.authorize(request).decision, "allow")
        self.assertEqual(
            policy.evaluate(
                ActionRequest(
                    "build",
                    "terminal.exec",
                    "process_execution",
                    command="npm install other",
                    argv=("npm", "install", "other"),
                )
            ).source,
            "session_grant",
        )
        self.assertEqual(
            Permissions({"approval_policy": "never"}).evaluate(request).decision, "deny"
        )
        self.assertEqual(
            Permissions({})
            .evaluate(
                ActionRequest(
                    "build",
                    "terminal.exec",
                    "process_execution",
                    command="sudo whoami",
                    argv=("sudo", "whoami"),
                )
            )
            .decision,
            "deny",
        )

    def test_full_profile_bypasses_rules_prompts_and_command_parsing(self):
        policy = Permissions(
            {
                "access_profile": "full",
                "approval_policy": "never",
                "rules": [{"pattern": ["git", "push"], "decision": "deny"}],
            }
        )
        for command in (
            "git push origin main",
            "npm install && node server.js",
            "sudo whoami",
        ):
            self.assertEqual(policy.decision("shell", command), "allow")

    def test_sbfl_scores_actual_counts(self):
        result = localize(
            [
                {"symbol": "bug", "failed": 2, "passed": 0},
                {"symbol": "other", "failed": 1, "passed": 3},
            ],
            2,
            3,
        )
        self.assertEqual(result[0]["symbol"], "bug")
        self.assertEqual(result[0]["score"], 1)

    def test_compaction_keeps_system_and_whole_tool_exchanges(self):
        class Provider:
            def chat(self, *args, **kwargs):
                return ProviderResponse(
                    content="Preserve public API; next inspect auth."
                )

        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old reply"},
            {"role": "user", "content": "current"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "read"}}]},
            {"role": "tool", "content": "code"},
            {"role": "tool", "content": "more code"},
        ]
        reduced, summary = compact(messages, Provider(), recent=2)
        self.assertEqual(reduced[0], messages[0])
        self.assertEqual(reduced[-3:], messages[-3:])
        self.assertIn("Preserve public API", summary)
