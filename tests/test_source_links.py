import unittest

from agent_barrage.core.events import make_event, valid_event
from agent_barrage.core.history import HistoryStore
from agent_barrage.core.settings import sanitize_settings


class SourceLinksTest(unittest.TestCase):
    def test_link_is_optional_and_rejects_unsafe_schemes_or_credentials(self):
        plain = make_event("my-agent", "done", "success", "完成")
        self.assertTrue(valid_event(plain))
        self.assertNotIn("open_url", plain)
        linked = make_event("my-agent", "done", "success", "完成",
                            open_url="https://example.com/tasks/123")
        self.assertTrue(valid_event(linked))
        for url in ("file:///etc/passwd", "javascript:alert(1)",
                    "https://user:secret@example.com/", "https://example.com/\nnext"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                make_event("my-agent", "done", "success", "完成", open_url=url)

    def test_privacy_mode_discards_source_link(self):
        history = HistoryStore()
        history.add("my-agent", "完成", "success", "真实", open_url="https://example.com/task")
        history.add("my-agent", "完成", "success", "真实", private=True,
                    open_url="https://example.com/task")
        self.assertEqual(history.recent()[0]["open_url"], "")
        self.assertEqual(history.recent()[1]["open_url"], "https://example.com/task")

    def test_display_preferences_validate(self):
        settings = sanitize_settings({"screens": "主屏幕", "reduce_motion": True})
        self.assertEqual(settings["screens"], "主屏幕")
        self.assertTrue(settings["reduce_motion"])
        self.assertEqual(sanitize_settings({"screens": "fake", "reduce_motion": "yes"})["screens"], "所有屏幕")


if __name__ == "__main__":
    unittest.main()
