import json
import tempfile
import unittest
from pathlib import Path

from unified_agent.config import load_config
from unified_agent.memory import Session
from unified_agent.permissions import Permissions
from unified_agent.provider import ProviderResponse
from unified_agent.runtime import MainAgent
from unified_agent.tools import ToolRegistry


def calls(*items):
    return ProviderResponse(
        tool_calls=[
            {"function": {"name": name, "arguments": args}} for name, args in items
        ]
    )


class FakeProvider:
    model = "fake"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.history = []

    def chat(self, messages, tools=None, **kwargs):
        self.history.append(
            {"messages": json.loads(json.dumps(messages)), "tools": tools}
        )
        item = next(self.responses)
        if isinstance(item, BaseException):
            raise item
        return item


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "calc.py").write_text(
            "def add(a, b):\n    return a - b\n", encoding="utf-8"
        )
        self.config = load_config(self.root)
        self.config["provider"]["stream"] = False
        self.config["agent"]["max_role_turns"] = 3
        self.session = Session(self.root)
        self.tools = ToolRegistry(
            self.root,
            self.session,
            Permissions({"shell": {"default": "allow"}}),
            self.config,
            emit=lambda *a, **k: None,
        )

    def agent(self, responses):
        return MainAgent(
            FakeProvider(responses),
            self.session,
            self.tools,
            self.config,
            emit=lambda *a, **k: None,
        )

    def test_standalone_question_returns_without_workspace_inspection(self):
        agent = self.agent(
            [
                ProviderResponse(
                    content="Use a strict parser and reject malformed offsets."
                )
            ]
        )
        agent.run("viết hàm parse timestamp ISO8601")
        self.assertEqual(self.session.data["state"], "READY")
        self.assertNotIn("route", self.session.data)
        names = {
            tool["function"]["name"] for tool in agent.provider.history[0]["tools"]
        }
        self.assertIn("workspace.context", names)
        self.assertIn("skill.load", names)
        self.assertNotIn("read", names)

    def test_model_selects_workspace_inspection_for_unseen_failure_phrase(self):
        agent = self.agent(
            [
                calls(("workspace.context", {})),
                ProviderResponse(
                    content="I found the available project facts and need the request details."
                ),
            ]
        )
        agent.run("second request returns 500 only under load")
        result = next(
            message
            for message in self.session.data["messages"]
            if message.get("tool_name") == "workspace.context"
        )
        self.assertTrue(json.loads(result["content"])["ok"])
        self.assertNotIn("language", result["content"])

    def test_model_can_build_in_existing_workspace_without_mode_switch(self):
        agent = self.agent(
            [
                calls(
                    ("fs.write", {"path": "tool.py", "content": "def main(): pass\n"})
                ),
                calls(
                    (
                        "submit",
                        {"summary": "Created the requested standalone CLI module."},
                    )
                ),
            ]
        )
        agent.run("this folder already has a README; create a small CLI tool here")
        self.assertEqual(self.session.data["state"], "READY")
        self.assertTrue((self.root / "tool.py").exists())

    def test_question_blocks_then_answer_resumes_same_session_context(self):
        agent = self.agent(
            [
                calls(
                    (
                        "user.question",
                        {"question": "Keep compatibility?", "options": ["yes", "no"]},
                    )
                ),
                ProviderResponse(content="Compatibility will be preserved."),
            ]
        )
        agent.run("Change the API")
        self.assertEqual(self.session.data["state"], "BLOCKED_USER")
        self.assertIn("pending_question", self.session.data)
        agent.run("yes")
        self.assertEqual(self.session.data["state"], "READY")
        self.assertNotIn("pending_question", self.session.data)
        self.assertNotIn("route", self.session.data)

    def test_subagent_is_model_selected_and_has_fresh_context(self):
        agent = self.agent(
            [
                calls(
                    (
                        "subagent",
                        {
                            "agent": "explore",
                            "task": "Locate the addition implementation.",
                        },
                    )
                ),
                ProviderResponse(content="calc.py contains add at line 1."),
                ProviderResponse(content="The implementation is in calc.py."),
            ]
        )
        agent.run("where is add implemented?")
        self.assertTrue((self.session.directory / "subagent-explore.md").exists())
        self.assertEqual(
            self.session.data["summary"], "The implementation is in calc.py."
        )
        self.assertEqual(len(agent.provider.history[1]["messages"]), 2)

    def test_subagent_profile_cannot_modify_source(self):
        agent = self.agent(
            [
                calls(("subagent", {"agent": "explore", "task": "Investigate calc."})),
                calls(
                    ("patch.apply", {"path": "calc.py", "old": "a - b", "new": "a + b"})
                ),
                ProviderResponse(content="Could not edit; the role is read-only."),
                ProviderResponse(content="Investigation complete."),
            ]
        )
        agent.run("investigate calc")
        self.assertIn("a - b", (self.root / "calc.py").read_text())

    def test_provider_error_persists_without_replaying_tool(self):
        agent = self.agent(
            [
                calls(
                    ("patch.apply", {"path": "calc.py", "old": "a - b", "new": "a + b"})
                ),
                RuntimeError("provider disconnected"),
            ]
        )
        agent.run("make transition atomic")
        self.assertEqual(self.session.data["state"], "ERROR")
        self.assertIn("a + b", (self.root / "calc.py").read_text())
        resumed = Session(self.root, self.session.run_id)
        self.assertEqual(resumed.data["state"], "ERROR")
        self.assertEqual(len(resumed.data["journal"]), 1)

    def test_agent_turns_are_unlimited_unless_configured(self):
        self.assertIsNone(self.config["agent"]["max_agent_turns"])
        agent = self.agent(
            [
                ProviderResponse(content="First response."),
                ProviderResponse(content="Second response."),
            ]
        )
        agent.run("first")
        agent.run("second")
        self.assertEqual(self.session.data["state"], "READY")

    def test_configured_agent_turn_cap_stops_a_run(self):
        self.config["agent"]["max_agent_turns"] = 1
        agent = self.agent(
            [
                calls(("workspace.context", {})),
                ProviderResponse(content="This request must not be made."),
            ]
        )
        agent.run("inspect once then continue")
        self.assertEqual(self.session.data["state"], "STEP_LIMIT")

    def test_plan_mode_hides_mutations_and_rejects_fabricated_write(self):
        self.session.data["collaboration_mode"] = "PLAN"
        names = {tool["function"]["name"] for tool in self.tools.schemas_for("build")}
        self.assertIn("plan.propose", names)
        self.assertNotIn("fs.write", names)
        result = self.tools.execute(
            "fs.write", {"path": "blocked.py", "content": "x = 1\n"}
        )
        self.assertFalse(result["ok"])
        self.assertFalse((self.root / "blocked.py").exists())

    def test_plan_mode_persists_a_model_proposal(self):
        self.session.data["collaboration_mode"] = "PLAN"
        agent = self.agent(
            [
                calls(
                    (
                        "plan.propose",
                        {
                            "summary": "Correct the calculation.",
                            "steps": [
                                {
                                    "title": "Change add",
                                    "files": ["calc.py"],
                                    "details": "Replace subtraction with addition.",
                                }
                            ],
                            "validation": ["Run test_calc"],
                            "open_questions": [],
                        },
                    )
                ),
                ProviderResponse(content="The proposed plan is ready."),
            ]
        )
        agent.run("Plan the calculation repair")
        self.assertEqual(
            self.session.data["proposed_plan"]["summary"],
            "Correct the calculation.",
        )
        self.assertFalse((self.root / "blocked.py").exists())

    def test_plan_mode_captures_text_when_model_omits_plan_tool(self):
        self.session.data["collaboration_mode"] = "PLAN"
        agent = self.agent(
            [
                ProviderResponse(
                    content="1. Update calc.py. 2. Run the regression test."
                ),
                ProviderResponse(content="The written plan is complete."),
            ]
        )
        agent.run("Plan the calculation repair")
        proposed = self.session.data["proposed_plan"]
        self.assertIsNotNone(proposed)
        self.assertIn("Update calc.py", proposed["steps"][0]["details"])
        self.assertEqual(self.session.data["state"], "READY")


if __name__ == "__main__":
    unittest.main()
