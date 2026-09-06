import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from unified_agent.memory import Session
from unified_agent.permissions import ActionRequest, Permissions
from unified_agent.skills import discover, load
from unified_agent.workspace import context, instructions


class GeneralizedCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_workspace_context_only_reports_boundaries_and_instruction_chain(self):
        (self.root / ".git").mkdir()
        (self.root / "AGENTS.md").write_text("root instruction\n")
        nested = self.root / "services" / "api"
        nested.mkdir(parents=True)
        (self.root / "services" / "AGENTS.md").write_text("service instruction\n")
        facts = context(nested).facts()
        self.assertEqual(facts["cwd"], str(nested))
        self.assertEqual(facts["git_root"], str(self.root))
        self.assertEqual(
            facts["instruction_files"], ["AGENTS.md", "services/AGENTS.md"]
        )
        self.assertNotIn("language", facts)
        self.assertNotIn("manifests", facts)
        self.assertNotIn("build_commands", facts)
        self.assertIn("service instruction", instructions(context(nested)))

    def test_skills_are_discoverable_and_project_skill_overrides_builtin(self):
        path = self.root / ".agent" / "skills" / "custom" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\ndescription: Project-specific guide\n---\n# Custom\n")
        self.assertIn("issue-resolution", discover(self.root))
        self.assertEqual(
            load(self.root, "custom")["content"].splitlines()[-1], "# Custom"
        )

    def test_permission_audit_and_once_grants_are_durable_and_not_persistent_rules(
        self,
    ):
        session = Session(self.root)
        policy = Permissions(
            {}, lambda *_: "once", root=self.root, session_id=session.run_id
        )
        request = ActionRequest(
            "build",
            "terminal.exec",
            "process_execution",
            command="npm install a",
            argv=("npm", "install", "a"),
        )
        self.assertEqual(policy.authorize(request).source, "user_once")
        self.assertEqual(
            policy.evaluate(
                ActionRequest(
                    "build",
                    "terminal.exec",
                    "process_execution",
                    command="npm install b",
                    argv=("npm", "install", "b"),
                )
            ).decision,
            "prompt",
        )
        with closing(
            sqlite3.connect(self.root / ".agent" / "permissions.sqlite3")
        ) as db:
            self.assertGreaterEqual(
                db.execute("SELECT COUNT(*) FROM permission_events").fetchone()[0], 3
            )
        with closing(sqlite3.connect(self.root / ".agent" / "sessions.sqlite3")) as db:
            self.assertEqual(
                db.execute("SELECT run_id FROM sessions").fetchone()[0], session.run_id
            )
