import unittest
from unittest.mock import Mock, patch

from unified_agent import cli


class ResumePromptTests(unittest.TestCase):
    def test_full_access_flag_is_available(self):
        self.assertTrue(cli.parse_args(["--full-access"]).full_access)

    def test_agent_turn_cap_is_optional_and_uses_the_public_flag(self):
        self.assertIsNone(cli.parse_args([]).max_agent_turns)
        self.assertEqual(
            cli.parse_args(["--max-agent-turns", "20"]).max_agent_turns, 20
        )

    def test_help_describes_interactive_commands_in_vietnamese(self):
        self.assertIn("/queue <yêu cầu>", cli.HELP)
        self.assertIn("/test <lệnh>", cli.HELP)
        self.assertIn("tiếp tục", cli.HELP)

    def test_resume_prompt_is_independent_from_permission_prompt(self):
        stdin = Mock()
        stdin.isatty.return_value = True
        with (
            patch.object(cli.sys, "stdin", stdin),
            patch("builtins.input", return_value="y"),
        ):
            self.assertTrue(cli.confirm_resume("run-123"))

    def test_resume_prompt_skips_noninteractive_input(self):
        stdin = Mock()
        stdin.isatty.return_value = False
        with patch.object(cli.sys, "stdin", stdin):
            self.assertFalse(cli.confirm_resume("run-123"))
