import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from unified_agent.provider import OllamaProvider


class Response:
    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(json.dumps(c).encode() + b"\n" for c in self.chunks)

    def read(self):
        return json.dumps(self.chunks[0]).encode()


class ProviderTests(unittest.TestCase):
    def test_stream_buffers_tool_fragments_and_does_not_render_thinking(self):
        chunks = [
            {
                "message": {
                    "content": "Hello",
                    "thinking": "private",
                    "tool_calls": [
                        {
                            "function": {
                                "index": 0,
                                "name": "read",
                                "arguments": '{"path":',
                            }
                        }
                    ],
                },
                "done": False,
            },
            {
                "message": {
                    "content": "!",
                    "tool_calls": [
                        {"function": {"index": 0, "arguments": '"main.py"}'}}
                    ],
                },
                "done": True,
                "eval_count": 3,
            },
        ]
        rendered = []
        provider = OllamaProvider("test", "http://localhost:11434")
        with patch("urllib.request.urlopen", return_value=Response(chunks)) as request:
            result = provider.chat([], stream=True, on_text=rendered.append)
        self.assertEqual(
            request.call_args.args[0].full_url, "http://localhost:11434/api/chat"
        )
        self.assertIsNone(request.call_args.args[0].get_header("Authorization"))
        self.assertEqual(rendered, ["Hello", "!"])
        self.assertEqual(result.thinking, "private")
        self.assertEqual(
            json.loads(result.tool_calls[0]["function"]["arguments"]),
            {"path": "main.py"},
        )
        self.assertEqual(result.usage, {"eval_count": 3})

    def test_incomplete_stream_never_returns_executable_tools(self):
        with patch(
            "urllib.request.urlopen",
            return_value=Response([{"message": {"content": "partial"}, "done": False}]),
        ):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                OllamaProvider("test", "http://localhost:11434/api").chat(
                    [], stream=True
                )

    def test_structured_schema_and_explicit_key(self):
        with patch(
            "urllib.request.urlopen",
            return_value=Response([{"message": {"content": "{}"}, "done": True}]),
        ) as request:
            OllamaProvider("model", "https://ollama.com/api", "test-only").chat(
                [], response_schema={"type": "object"}
            )
        req = request.call_args.args[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer test-only")
        self.assertEqual(json.loads(req.data)["format"], {"type": "object"})

    def test_invalid_endpoint_rejected(self):
        for url in (
            "file:///etc/passwd",
            "http://name:secret@host",
            "http://host?key=secret",
        ):
            with self.assertRaises(ValueError):
                OllamaProvider("test", url)

    def test_transient_cloud_error_retries_before_failing(self):
        failure = HTTPError("https://ollama.com/api/chat", 500, "error", {}, BytesIO())
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=[
                    failure,
                    Response([{"message": {"content": "OK"}, "done": True}]),
                ],
            ) as request,
            patch("unified_agent.provider.time.sleep") as sleep,
        ):
            result = OllamaProvider("test", "https://ollama.com/api").chat([])
        self.assertEqual(result.content, "OK")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1)
