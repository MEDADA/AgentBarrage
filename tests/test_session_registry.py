"""Session state follows evidence; missing or delayed hooks cannot invent outcomes."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_marquee.core.event_v2 import make_event_v2
from agent_marquee.core.events import make_event
from agent_marquee.core.registry import SessionRegistry


def signal(event_type, *, session="s1", turn="t1", agent="codex", **fields):
    return make_event_v2(
        agent, event_type, event_type, session_id=session, turn_id=turn, **fields)


class SessionRegistryTest(unittest.TestCase):
    def test_multiple_sources_and_sessions_are_separate(self):
        registry = SessionRegistry()
        for agent in ("codex", "claude-code"):
            for session in ("a", "b", "c", "d"):
                registry.ingest(signal("prompt_submitted", agent=agent, session=session), received_at=10)
        items = registry.work_items(now=11)
        self.assertEqual(len(items), 8)
        self.assertEqual({item.state for item in items}, {"submitted"})
        self.assertEqual(len({item.key for item in items}), 8)

    def test_tool_end_and_stop_do_not_complete_work(self):
        registry = SessionRegistry()
        registry.ingest(signal("prompt_submitted"), received_at=10)
        registry.ingest(signal("tool_started"), received_at=11)
        registry.ingest(signal("tool_finished"), received_at=12)
        item = registry.ingest(signal("turn_stop_observed"), received_at=13)
        self.assertEqual(item.state, "unknown")
        self.assertTrue(item.stop_observed)

    def test_subagent_stop_is_not_whole_task_completion(self):
        registry = SessionRegistry()
        registry.ingest(signal("subagent_started", task_id="child"), received_at=10)
        item = registry.ingest(signal("subagent_finished", task_id="child"), received_at=11)
        self.assertNotEqual(item.state, "completed")

    def test_approval_request_is_tentative_until_visible(self):
        registry = SessionRegistry()
        tentative = registry.ingest(signal("approval_requested"), received_at=10)
        self.assertEqual(tentative.state, "unknown")
        self.assertEqual(tentative.attention, "approval")
        self.assertEqual(tentative.attention_confidence, "tentative")
        confirmed = registry.ingest(signal("approval_visible"), received_at=11)
        self.assertEqual(confirmed.state, "waiting_approval")
        self.assertEqual(confirmed.attention_confidence, "confirmed")

    def test_duplicate_and_older_sequence_are_ignored(self):
        registry = SessionRegistry()
        first = signal("prompt_submitted", sequence=2)
        self.assertEqual(registry.ingest(first, received_at=10).state, "submitted")
        self.assertIsNone(registry.ingest(first, received_at=11))
        self.assertIsNone(registry.ingest(signal("tool_started", sequence=1), received_at=12))
        self.assertEqual(registry.work_items(now=13)[0].state, "submitted")

    def test_terminal_state_resists_late_progress_and_new_turn_is_independent(self):
        registry = SessionRegistry()
        registry.ingest(signal("prompt_submitted"), received_at=10)
        registry.ingest(signal("turn_failed"), received_at=11)
        late = registry.ingest(signal("tool_started"), received_at=12)
        self.assertEqual(late.state, "failed")
        new_turn = registry.ingest(signal("prompt_submitted", turn="t2"), received_at=13)
        self.assertEqual(new_turn.state, "submitted")
        self.assertEqual(len(registry.work_items(now=14)), 2)

    def test_missing_identity_stays_notification_only(self):
        registry = SessionRegistry()
        self.assertIsNone(registry.ingest(signal("tool_started", session=""), received_at=10))
        self.assertIsNone(registry.ingest(signal("notification", agent="wechat"), received_at=11))
        self.assertEqual(registry.work_items(now=12), [])

    def test_stale_is_health_not_blocked_and_session_end_is_unknown(self):
        registry = SessionRegistry(stale_after=10)
        registry.ingest(signal("tool_started"), received_at=10)
        item = registry.work_items(now=21)[0]
        self.assertEqual((item.state, item.health), ("working", "stale"))
        registry.ingest(signal("session_ended"), received_at=22)
        ended = registry.work_items(now=23)[0]
        self.assertEqual(ended.state, "unknown")
        self.assertEqual(registry.session_status("codex", "", "s1"), "ended")

    def test_late_event_cannot_reopen_ended_session(self):
        registry = SessionRegistry()
        registry.ingest(signal("tool_started"), received_at=10)
        registry.ingest(signal("session_ended"), received_at=11)
        self.assertIsNone(registry.ingest(signal("tool_finished"), received_at=12))
        self.assertEqual(registry.session_status("codex", "", "s1"), "ended")
        self.assertEqual(registry.work_items(now=13)[0].state, "unknown")

    def test_v1_stop_uses_observation_mapping(self):
        registry = SessionRegistry()
        legacy = make_event("codex", "Stop", "success", "任务已完成", "Demo", "s1", "t1")
        item = registry.ingest(legacy, received_at=10)
        self.assertEqual(item.state, "unknown")
        self.assertTrue(item.stop_observed)

    def test_later_tool_activity_clears_tentative_approval(self):
        registry = SessionRegistry()
        registry.ingest(signal("approval_requested"), received_at=10)
        item = registry.ingest(signal("tool_started"), received_at=11)
        self.assertEqual(item.state, "working")
        self.assertEqual(item.attention, "")

    def test_invalid_event_is_rejected_without_crashing_or_tracking(self):
        registry = SessionRegistry()
        with self.assertRaises(ValueError):
            registry.ingest(None)
        self.assertEqual(registry.work_items(now=11), [])

    def test_registry_evicts_oldest_session_with_its_work(self):
        registry = SessionRegistry(max_sessions=2)
        for index, session in enumerate(("s1", "s2", "s3")):
            registry.ingest(signal("prompt_submitted", session=session), received_at=10 + index)
        self.assertEqual({item.key[2] for item in registry.work_items(now=14)}, {"s2", "s3"})
        self.assertEqual(registry.session_status("codex", "", "s1"), "unknown")


if __name__ == "__main__":
    unittest.main()
