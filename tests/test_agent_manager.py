import time
import unittest

from unified_agent.agent_manager import AgentManager, AgentState


class AgentManagerTests(unittest.TestCase):
    def test_spawn_send_wait_resume_and_close(self):
        def runner(handle):
            time.sleep(0.01)
            return {"task": handle.task, "messages": list(handle.inbox)}

        manager = AgentManager(runner, max_agents=2)
        first = manager.spawn("explore", "Inspect auth")
        second = manager.spawn("reviewer", "Review diff")
        manager.send(first.agent_id, "Also inspect frontend")
        rows = manager.wait([first.agent_id, second.agent_id])
        self.assertEqual({row["status"] for row in rows}, {AgentState.COMPLETE})
        resumed = manager.resume(first.agent_id, "Check tests")
        self.assertEqual(resumed.state, AgentState.RUNNING)
        self.assertEqual(
            manager.wait([first.agent_id])[0]["status"], AgentState.COMPLETE
        )
        manager.close(second.agent_id)
        self.assertEqual(manager.handles[second.agent_id].state, AgentState.CLOSED)
