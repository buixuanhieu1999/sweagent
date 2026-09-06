import tempfile
import unittest
from pathlib import Path

from unified_agent.code_intelligence import CodeIntelligenceService
from unified_agent.config import load_config
from unified_agent.memory import Session
from unified_agent.permissions import Permissions
from unified_agent.tools import ToolRegistry


class WorkspaceIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / ".git").mkdir()
        (self.root / "frontend").mkdir()
        (self.root / "backend").mkdir()

    def test_generic_code_service_uses_fallback_without_language_server(self):
        source = self.root / "backend" / "payment.cs"
        source.write_text(
            "public class PaymentService {\n  public void Charge() {}\n}\n"
        )
        service = CodeIntelligenceService(self.root, load_config(self.root))
        symbols = service.symbols("Payment")
        self.assertEqual(symbols["backend"], "generic")
        self.assertEqual(symbols["result"][0]["symbol"], "PaymentService")
        definition = service.definition("backend/payment.cs", 1, 15)
        self.assertEqual(definition["backend"], "generic")
        self.assertEqual(definition["query"], "PaymentService")

    def test_tools_expose_generic_workspace_and_code_capabilities_with_monorepo_cwd(
        self,
    ):
        nested = self.root / "backend"
        tools = ToolRegistry(
            nested,
            Session(nested),
            Permissions(),
            load_config(nested),
            emit=lambda *args, **kwargs: None,
        )
        names = {item["function"]["name"] for item in tools.schemas_for()}
        self.assertIn("workspace.context", names)
        self.assertNotIn("code.definition", names)
        self.assertNotIn("code.lsp", names)
        self.assertTrue(
            tools.execute("tool.search", {"query": "code definition"})["ok"]
        )
        names = {item["function"]["name"] for item in tools.schemas_for()}
        self.assertIn("code.definition", names)
        self.assertIn("code.symbols", names)
        self.assertEqual(tools._cwd("frontend"), self.root / "frontend")
        self.assertFalse(
            tools.execute("workspace.context", {})["result"].get("language")
        )

    def test_project_extension_registers_as_a_deferred_tool(self):
        extension = self.root / ".agent" / "extensions" / "echo.py"
        extension.parent.mkdir(parents=True)
        extension.write_text(
            "from unified_agent.extensions import ExtensionTool\n"
            "class Extension:\n"
            "    def tools(self):\n"
            "        return [ExtensionTool('demo.echo', 'Echo text', {'text': {'type': 'string'}}, lambda args: args)]\n"
            "extension = Extension()\n"
        )
        tools = ToolRegistry(
            self.root,
            Session(self.root),
            Permissions(),
            load_config(self.root),
            emit=lambda *args, **kwargs: None,
        )
        self.assertNotIn(
            "demo.echo", {item["function"]["name"] for item in tools.schemas_for()}
        )
        tools.execute("tool.search", {"query": "demo echo"})
        self.assertIn(
            "demo.echo", {item["function"]["name"] for item in tools.schemas_for()}
        )
        self.assertEqual(
            tools.execute("demo.echo", {"text": "ok"})["result"], {"text": "ok"}
        )
