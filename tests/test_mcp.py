import sys
import tempfile
import unittest
from pathlib import Path

from unified_agent.mcp import MCPManager


SERVER = """import json, sys
for line in sys.stdin:
    message = json.loads(line)
    method = message['method']
    if method == 'tools/list':
        result = {'tools': [{'name': 'echo', 'description': 'Echo', 'inputSchema': {'properties': {'text': {'type': 'string'}}}}]}
    elif method == 'tools/call':
        result = {'content': [{'type': 'text', 'text': message['params']['arguments']['text']}]}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}), flush=True)
"""


class MCPTests(unittest.TestCase):
    def test_configured_server_discovers_and_invokes_namespaced_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            server = root / "server.py"
            server.write_text(SERVER)
            config = root / ".agent" / "mcp.yaml"
            config.parent.mkdir()
            config.write_text(
                "servers:\n  demo:\n    command: ["
                + repr(sys.executable)
                + ", "
                + repr(str(server))
                + "]\n"
            )
            manager = MCPManager(root)
            try:
                tools = manager.connect("demo")
                self.assertEqual(tools[0].name, "mcp.demo.echo")
                self.assertEqual(
                    tools[0].executor({"text": "hello"})["content"][0]["text"],
                    "hello",
                )
            finally:
                manager.disconnect("demo")
