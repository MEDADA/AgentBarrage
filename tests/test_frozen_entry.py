import sys
import unittest
from unittest.mock import patch

from agent_marquee.install import command_for, is_our_handler


class FrozenEntryTest(unittest.TestCase):
    def test_packaged_hook_command_uses_headless_dispatch(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", "/Applications/AgentMarquee.app/Contents/MacOS/AgentMarquee"):
            command = command_for("codex")
        self.assertIn("--hook-adapter codex", command)
        self.assertTrue(is_our_handler({"command": command}, "codex"))
        self.assertFalse(is_our_handler({"command": command}, "claude-code"))


if __name__ == "__main__":
    unittest.main()
