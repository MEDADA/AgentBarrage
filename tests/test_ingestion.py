"""State ingestion is independent of presentation throttling."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_marquee.core.event_v2 import make_event_v2
from agent_marquee.core.ingestion import IngestionEngine


class IngestionTest(unittest.TestCase):
    def test_progress_updates_state_even_if_presentation_is_suppressed(self):
        ingestion = IngestionEngine()
        event = make_event_v2("codex", "tool_started", "正在调用工具",
                              session_id="s1", turn_id="t1")
        ingestion.ingest(event, received_at=10)
        decisions = ingestion.decisions(now=11)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].label, "正在工作")

    def test_privacy_discards_existing_and_incoming_state(self):
        ingestion = IngestionEngine()
        event = make_event_v2("codex", "prompt_submitted", "收到任务",
                              session_id="s1", turn_id="t1")
        ingestion.ingest(event, received_at=10)
        ingestion.clear()
        ingestion.ingest(event, private=True, received_at=11)
        self.assertEqual(ingestion.decisions(now=12), [])


if __name__ == "__main__":
    unittest.main()
