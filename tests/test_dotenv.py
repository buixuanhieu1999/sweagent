import os
import tempfile
import unittest
from pathlib import Path

import agent


class DotenvTests(unittest.TestCase):
    def test_loads_ollama_values_without_overwriting_existing_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "OLLAMA_API_KEY=from-file\nOLLAMA_MODEL=example\nUNRELATED=value\n",
                encoding="utf-8",
            )
            original_key = os.environ.pop("OLLAMA_API_KEY", None)
            original_model = os.environ.pop("OLLAMA_MODEL", None)
            try:
                agent.load_dotenv(path)
                self.assertEqual(os.environ["OLLAMA_API_KEY"], "from-file")
                self.assertEqual(os.environ["OLLAMA_MODEL"], "example")
                os.environ["OLLAMA_API_KEY"] = "from-environment"
                agent.load_dotenv(path)
                self.assertEqual(os.environ["OLLAMA_API_KEY"], "from-environment")
            finally:
                os.environ.pop("OLLAMA_API_KEY", None)
                if original_key is not None:
                    os.environ["OLLAMA_API_KEY"] = original_key
                if original_model is None:
                    os.environ.pop("OLLAMA_MODEL", None)
                else:
                    os.environ["OLLAMA_MODEL"] = original_model


if __name__ == "__main__":
    unittest.main()
