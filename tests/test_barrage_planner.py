"""State decisions determine which agent observations reach the overlay."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_marquee.core.barrage import BarragePlanner
from agent_marquee.core.event_v2 import make_event_v2
from agent_marquee.core.ingestion import IngestionEngine


class BarragePlannerTest(unittest.TestCase):
    def setUp(self):
        self.ingestion = IngestionEngine()
        self.planner = BarragePlanner(self.ingestion)

    def event(self, event_type, summary, *, session="s1", event_id=None,
              kind="working"):
        return make_event_v2("codex", event_type, summary, session_id=session,
                             turn_id="t1", event_id=event_id,
                             presentation_kind=kind)

    def test_attention_uses_state_label_and_precedes_routine(self):
        routine = self.event("tool_started", "正在做事", session="s2")
        tentative = self.event("approval_requested", "需要批准", kind="attention")
        shown = self.planner.plan([routine, tentative], progress_mode="全部", now=10)
        self.assertEqual([entry["message"] for entry in shown],
                         ["可能需要批准", "正在做事"])
        self.assertEqual(shown[0]["kind"], "attention")

    def test_repeated_attention_is_coalesced_per_work_item(self):
        first = self.event("approval_requested", "可能需要批准", event_id="a")
        repeat = self.event("approval_requested", "仍需批准", event_id="b")
        self.assertEqual(len(self.planner.plan([first], now=10)), 1)
        self.assertEqual(self.planner.plan([repeat], now=11), [])
        other = self.event("approval_requested", "可能需要批准", session="s2")
        self.assertEqual(len(self.planner.plan([other], now=12)), 1)

    def test_paused_and_private_hide_barrage_but_state_is_conservative(self):
        paused = self.event("approval_requested", "敏感请求", event_id="a")
        self.assertEqual(self.planner.plan([paused], paused=True, now=10), [])
        self.assertEqual(self.ingestion.decisions(now=11)[0].label, "可能需要批准")
        self.ingestion.clear()
        private = self.event("approval_requested", "敏感请求", event_id="b")
        self.assertEqual(self.planner.plan([private], private=True, now=12), [])
        self.assertEqual(self.ingestion.decisions(now=13), [])

    def test_duplicate_event_id_does_not_repeat_barrage(self):
        event = self.event("tool_started", "正在做事", event_id="a")
        self.assertEqual(len(self.planner.plan([event], progress_mode="全部", now=10)), 1)
        self.assertEqual(self.planner.plan([event], progress_mode="全部", now=12), [])

    def test_sessionless_notification_keeps_legacy_display_path(self):
        notice = make_event_v2("pager", "notification", "新消息",
                               session_id="", presentation_kind="attention")
        shown = self.planner.plan([notice], now=10)
        self.assertEqual([entry["message"] for entry in shown], ["新消息"])

    def test_same_batch_resolution_does_not_show_old_approval(self):
        request = self.event("approval_requested", "需要批准", event_id="a",
                             kind="attention")
        progress = self.event("tool_started", "继续工作", event_id="b")
        shown = self.planner.plan([request, progress], progress_mode="全部", now=10)
        self.assertEqual([entry["message"] for entry in shown], ["继续工作"])

    def test_important_state_bypasses_routine_filter(self):
        request = self.event("approval_requested", "需要批准", kind="attention")
        shown = self.planner.plan([request], filter_mode="只看需处理", now=10)
        self.assertEqual([entry["message"] for entry in shown], ["可能需要批准"])

    def test_session_end_keeps_notification(self):
        ending = self.event("session_ended", "会话已结束", kind="success")
        shown = self.planner.plan([ending], now=10)
        self.assertEqual([entry["message"] for entry in shown], ["会话已结束"])


if __name__ == "__main__":
    unittest.main()
