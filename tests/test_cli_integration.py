"""Real HTTP + subprocess tests, with a deterministic Ollama-compatible server."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class CliIntegrationTests(unittest.TestCase):
    def test_interactive_repair_real_fail_before_pass_after_and_followup(self):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, payload, stream=False):
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/x-ndjson" if stream else "application/json",
                )
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode() + b"\n")

            def do_GET(self):
                self.respond({"models": [{"name": "fake"}]})

            def do_POST(self):
                request = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                observed.append(request)
                messages = request["messages"]
                system = messages[0]["content"]
                message = {"role": "assistant", "content": ""}

                def call(name, args):
                    message["tool_calls"] = [
                        {"function": {"name": name, "arguments": args}}
                    ]

                if request.get("format"):
                    message["content"] = '{"approved":true,"findings":[]}'
                elif "Your bounded role:" in system:
                    if (
                        "matching" in system.split("Your bounded role:")[1]
                        or "Find and run a targeted test" in system
                    ):
                        if any(m.get("tool_name") == "test" for m in messages):
                            message["content"] = (
                                "Reproduced: add returned -1 rather than 3."
                            )
                        else:
                            call(
                                "test",
                                {
                                    "command": "python -m unittest test_calc -v",
                                    "stage": "reproduction",
                                },
                            )
                    else:
                        message["content"] = (
                            "Inspected calc.py and regression test; evidence is consistent."
                        )
                elif any(m.get("content") == "explain calc.py" for m in messages):
                    message["content"] = "The add function now returns the sum."
                else:
                    results = [
                        m.get("tool_name") for m in messages if m["role"] == "tool"
                    ]
                    if "patch" not in results:
                        call(
                            "patch", {"path": "calc.py", "old": "a - b", "new": "a + b"}
                        )
                    elif "test" not in results:
                        call("test", {"command": "python -m unittest test_calc -v"})
                    else:
                        call("submit", {"summary": "Fixed add; regression passes."})
                self.respond(
                    {"message": message, "done": True}, request.get("stream", False)
                )

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "calc.py").write_text("def add(a, b):\n    return a - b\n")
                (root / "test_calc.py").write_text(
                    "import unittest\nfrom calc import add\nclass TestAdd(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(1, 2), 3)\n"
                )
                (root / ".agent").mkdir()
                (root / ".agent" / "permissions.yaml").write_text(
                    "shell:\n  default: allow\n"
                )
                env = {
                    **os.environ,
                    "PYTHONUTF8": "1",
                    "OLLAMA_API_KEY": "must-not-be-sent-locally",
                }
                result = subprocess.run(
                    [
                        sys.executable,
                        "agent.py",
                        "--repo",
                        str(root),
                        "--host",
                        f"http://127.0.0.1:{server.server_port}",
                        "--model",
                        "fake",
                        "--shell",
                        "powershell" if os.name == "nt" else "bash",
                        "--new-session",
                    ],
                    input="fix bug in add\nexplain calc.py\n/status\n/exit\n",
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    timeout=45,
                    env=env,
                    cwd=Path(__file__).resolve().parents[1],
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Fixed add; regression passes.", result.stdout)
                self.assertIn("The add function now returns the sum.", result.stdout)
                states = list((root / ".agent" / "runs").glob("*/state.json"))
                self.assertEqual(len(states), 1)
                state = json.loads(states[0].read_text(encoding="utf-8"))
                self.assertEqual(state["turn"], 2)
                self.assertEqual(state["state"], "READY")
                self.assertEqual([v["exit_code"] for v in state["validation"]], [0])
                self.assertIn("a + b", (root / "calc.py").read_text())
                self.assertGreaterEqual(len(observed), 4)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
