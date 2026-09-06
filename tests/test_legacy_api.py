import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AgentTests(unittest.TestCase):
    def test_extracts_object_and_json_string_arguments(self):
        self.assertEqual(
            agent.arguments_for({"function": {"arguments": {"command": "dir"}}}),
            {"command": "dir"},
        )
        self.assertEqual(
            agent.arguments_for({"function": {"arguments": '{"summary":"done"}'}}),
            {"summary": "done"},
        )
        self.assertEqual(
            agent.arguments_for({"function": {"arguments": "invalid"}}), {}
        )

    def test_dry_run_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = agent.run_bash(
                "this-command-does-not-exist",
                Path(directory),
                1,
                True,
                ["unused-shell"],
            )
        self.assertEqual(result, "[dry-run: command not executed]")

    def test_chat_uses_native_ollama_endpoint_and_bearer_key(self):
        captured = {}

        def fake_open(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"message": {"role": "assistant", "content": "ok"}})

        with patch("urllib.request.urlopen", fake_open):
            response = agent.chat(
                "https://ollama.com/api", "test-key", {"model": "test", "stream": False}
            )
        self.assertEqual(response["message"]["content"], "ok")
        self.assertEqual(captured["url"], "https://ollama.com/api/chat")
        self.assertEqual(captured["authorization"], "Bearer test-key")
        self.assertEqual(captured["body"]["model"], "test")


if __name__ == "__main__":
    unittest.main()
