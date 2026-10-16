"""Offline transport and cross-source recovery at the ingestion boundary."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_marquee.core import spool
from agent_marquee.core.events import make_event
from agent_marquee.core.ingestion import IngestionEngine


class TransportLifecycleTest(unittest.TestCase):
    def test_offline_events_from_two_agents_recover_as_separate_tasks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                spool, "SPOOL_DIR", Path(directory) / "events"):
            for agent in ("codex", "claude-code"):
                event = make_event(agent, "UserPromptSubmit", "working", "收到任务",
                                   "Project", "shared-session")
                self.assertTrue(spool.publish(event))
            ingestion = IngestionEngine()
            for event in spool.drain():
                ingestion.ingest(event)
            decisions = ingestion.decisions()
            self.assertEqual({item.work_key[0] for item in decisions},
                             {"codex", "claude-code"})
            self.assertEqual([item.label for item in decisions], ["已接收", "已接收"])
            self.assertEqual(spool.drain(), [])

    def test_old_spool_file_does_not_replay_with_fresh_event_timestamp(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                spool, "SPOOL_DIR", Path(directory) / "events"):
            event = make_event("codex", "UserPromptSubmit", "working", "收到任务",
                               "Project", "session")
            self.assertTrue(spool.publish(event))
            old = time.time() - spool.MAX_AGE_SECONDS - 2
            for path in spool.SPOOL_DIR.glob("*.json"):
                os.utime(path, (old, old))
            self.assertEqual(spool.drain(), [])

    def test_future_event_timestamp_does_not_extend_queue_lifetime(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                spool, "SPOOL_DIR", Path(directory) / "events"):
            event = make_event("codex", "UserPromptSubmit", "working", "收到任务",
                               "Project", "session")
            event["occurred_at"] = time.time() + 3600
            self.assertTrue(spool.publish(event))
            self.assertEqual(spool.drain(), [])


if __name__ == "__main__":
    unittest.main()
