import tempfile
import unittest
from pathlib import Path

from unified_agent.memory import Session
from unified_agent.turns import SessionRuntime, ToolLoopGuard, TurnState


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

    def test_loop_guard_warns_then_blocks_identical_calls(self):
        guard = ToolLoopGuard(self.session)
        for _ in range(2):
            self.assertIsNone(guard.before("search.grep", {"query": "auth"}))
            guard.record("search.grep", {"query": "auth"}, {"ok": True})
        self.assertIn("warning", guard.before("search.grep", {"query": "auth"}))
        guard.record("search.grep", {"query": "auth"}, {"ok": True})
        self.assertIn("Loop detected", guard.before("search.grep", {"query": "auth"}))
