"""Attention ordering is deterministic and keeps uncertain signals distinct."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_marquee.core.attention import AttentionEngine, format_attention_rows
from agent_marquee.core.event_v2 import make_event_v2
from agent_marquee.core.registry import SessionRegistry


class AttentionTest(unittest.TestCase):
    def test_prioritizes_confirmed_human_requests(self):
        registry = SessionRegistry()
        signals = [
            ("working", "tool_started"),
            ("approval", "approval_visible"),
            ("input", "input_requested"),
            ("failure", "turn_failed"),
            ("tentative", "approval_requested"),
        ]
        for session, event_type in signals:
            registry.ingest(make_event_v2("codex", event_type, session,
                                          project="Demo", session_id=session,
                                          turn_id="t1"), received_at=10)
        decisions = AttentionEngine().decide(registry.work_items(now=11), now=11)
        self.assertEqual([decision.work_key[2] for decision in decisions],
                         ["approval", "input", "failure", "tentative", "working"])
        self.assertTrue(decisions[0].needs_action)
        self.assertFalse(decisions[3].needs_action)
        self.assertEqual(decisions[3].confidence, "tentative")
        self.assertEqual(decisions[0].project, "Demo")

    def test_privacy_and_pause_hide_task_details(self):
        registry = SessionRegistry()
        registry.ingest(make_event_v2("codex", "approval_visible", "敏感工作",
                                      project="Secret", session_id="s1"), received_at=10)
        items = registry.work_items(now=11)
        engine = AttentionEngine()
        self.assertEqual(engine.decide(items, private=True), [])
        self.assertEqual(engine.decide(items, paused=True), [])

    def test_stale_running_is_not_misreported_as_blocked(self):
        registry = SessionRegistry(stale_after=5)
        registry.ingest(make_event_v2("codex", "tool_started", "正在运行",
                                      session_id="s1"), received_at=10)
        decision = AttentionEngine().decide(registry.work_items(now=20))[0]
        self.assertEqual(decision.label, "状态未确认")
        self.assertFalse(decision.needs_action)

    def test_task_list_distinguishes_tentative_from_confirmed(self):
        registry = SessionRegistry()
        registry.ingest(make_event_v2("codex", "approval_requested", "需要批准操作",
                                      session_id="s1", project="Demo"), received_at=10)
        rows = format_attention_rows(AttentionEngine().decide(registry.work_items(now=11), now=11))
        self.assertIn("可能需要批准", rows)
        self.assertIn("Demo", rows)
        self.assertNotIn("\n需要批准\n", rows)

    def test_tentative_approval_expires_without_becoming_confirmed(self):
        registry = SessionRegistry()
        registry.ingest(make_event_v2("codex", "approval_requested", "可能需要批准",
                                      session_id="s1"), received_at=10)
        item = registry.work_items(now=50)
        decision = AttentionEngine(tentative_ttl=30).decide(item, now=50)[0]
        self.assertEqual(decision.label, "状态未确认")
        self.assertFalse(decision.needs_action)


if __name__ == "__main__":
    unittest.main()
