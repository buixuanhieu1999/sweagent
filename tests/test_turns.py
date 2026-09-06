import tempfile
import unittest
from pathlib import Path

from unified_agent.memory import Session
from unified_agent.turns import (
    CollaborationMode,
    SessionRuntime,
    ToolLoopGuard,
    TurnState,
)


class TurnRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = Session(Path(self.temp.name).resolve())
        self.runtime = SessionRuntime(self.session)

    def test_plan_is_mutable_context_not_executable_state(self):
        self.runtime.start("Repair the login flow")
        steps = self.runtime.update_plan(
            [
                {"text": "Inspect evidence", "status": "completed"},
                {"text": "Choose next action", "status": "in_progress"},
            ]
        )
        self.assertEqual(self.session.data["plan"], steps)
        self.assertEqual(self.runtime.active()["status"], TurnState.RUNNING)
        with self.assertRaisesRegex(ValueError, "at most one"):
            self.runtime.update_plan(
                [
                    {"text": "A", "status": "in_progress"},
                    {"text": "B", "status": "in_progress"},
                ]
            )

    def test_question_blocks_and_answer_resumes_the_same_turn(self):
        turn = self.runtime.start("Change the API")
        self.runtime.question("Keep v1?", ["yes", "no"])
        self.assertEqual(self.runtime.active()["id"], turn["id"])
        self.assertEqual(self.session.data["state"], TurnState.BLOCKED_USER)
        answer = self.runtime.answer("yes")
        self.assertIn("yes", answer)
        self.assertEqual(self.runtime.active()["id"], turn["id"])

    def test_plan_mode_and_proposed_plan_are_persisted_separately(self):
        self.runtime.set_mode(CollaborationMode.PLAN)
        proposed = self.runtime.propose(
            {
                "summary": "Add a health endpoint.",
                "steps": [
                    {
                        "title": "Add route",
                        "files": ["app.py"],
                        "details": "Register GET /health.",
                    }
                ],
                "validation": ["Run unit tests"],
                "open_questions": [],
            }
        )
        self.assertEqual(
            self.session.data["collaboration_mode"], CollaborationMode.PLAN
        )
        self.assertEqual(self.session.data["proposed_plan"], proposed)
        self.assertEqual(self.session.data["plan"], [])

    def test_session_list_and_delete(self):
        other = Session(self.session.root)
        records = Session.list(self.session.root)
        self.assertEqual(
            {record["id"] for record in records}, {self.session.run_id, other.run_id}
        )
        Session.delete(self.session.root, other.run_id)
        self.assertEqual(
            [record["id"] for record in Session.list(self.session.root)],
            [self.session.run_id],
        )

    def test_loop_guard_warns_then_blocks_identical_calls(self):
        guard = ToolLoopGuard(self.session)
        for _ in range(2):
            self.assertIsNone(guard.before("search.grep", {"query": "auth"}))
            guard.record("search.grep", {"query": "auth"}, {"ok": True})
        self.assertIn("warning", guard.before("search.grep", {"query": "auth"}))
        guard.record("search.grep", {"query": "auth"}, {"ok": True})
        self.assertIn("Loop detected", guard.before("search.grep", {"query": "auth"}))
