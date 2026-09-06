import unittest
from unittest.mock import patch

from unified_agent import external


class ExternalCapabilityTests(unittest.TestCase):
    def test_fetch_cleans_html_and_validates_url(self):
        with patch.object(
            external,
            "_download",
            return_value=("<h1>Hello</h1><p>world</p>", "https://example.test"),
        ):
            result = external.fetch("https://example.test")
        self.assertEqual(result["url"], "https://example.test")
        self.assertEqual(result["text"], "Hello world")
        with self.assertRaises(ValueError):
            external.fetch("file:///secret")
