import sys
import tempfile
import unittest
from pathlib import Path

from unified_agent.lsp import query
from unified_agent.search import coverage_spectra, localize


SERVER = r"""
import json, sys
while True:
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line: sys.exit(0)
        if line == b"\r\n": break
        key, value = line.decode().split(":", 1)
        headers[key.lower()] = value.strip()
    message = json.loads(sys.stdin.buffer.read(int(headers["content-length"])))
    if message.get("method") == "exit": break
    if "id" not in message: continue
    result = [{"name": "add", "kind": 12}] if message["method"] == "textDocument/documentSymbol" else {}
    data = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
    sys.stdout.buffer.flush()
"""


class LspCoverageTests(unittest.TestCase):
    def test_lsp_framing_initialize_open_query_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            server = root / "server.py"
            server.write_text(SERVER)
            code = root / "code.py"
            code.write_text("def add(a, b): return a + b\n")
            result = query(
                root, code, [sys.executable, str(server)], "symbols", timeout=3
            )
            self.assertEqual(result, [{"name": "add", "kind": 12}])

    def test_coverage_contexts_convert_to_real_spectra(self):
        report = {
            "files": {
                "calc.py": {"contexts": {"1": ["passing", "failing"], "2": ["failing"]}}
            }
        }
        spectra = coverage_spectra(report, ["failing"], ["passing"])
        ranked = localize(**spectra)
        self.assertEqual(ranked[0]["symbol"], "calc.py:2")
        self.assertEqual(ranked[0]["score"], 1)
        with self.assertRaises(ValueError):
            coverage_spectra(report, ["unknown-test"], ["passing"])
