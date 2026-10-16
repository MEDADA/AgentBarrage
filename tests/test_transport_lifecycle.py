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
    def test_offline_events_replay_as_notifications_without_false_live_tasks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                spool, "SPOOL_DIR", Path(directory) / "events"):
            for agent in ("codex", "claude-code"):
                event = make_event(agent, "UserPromptSubmit", "working", "收到任务",
                                   "Project", "shared-session")
                self.assertTrue(spool.publish(event))
            startup = time.time()
            ingestion = IngestionEngine(started_at=startup)
            replayed = spool.drain()
            self.assertEqual({event["agent"] for event in replayed},
                             {"codex", "claude-code"})
            for event in replayed:
                ingestion.ingest(event)
            self.assertEqual(ingestion.decisions(), [])
            self.assertEqual(spool.drain(), [])

            live = make_event("codex", "PreToolUse", "working", "正在工作",
                              "Project", "shared-session")
            live["occurred_at"] = startup + 1
            ingestion.ingest(live)
            self.assertEqual(ingestion.decisions()[0].label, "正在工作")

    def test_spool_is_bounded_even_when_periodic_random_pruning_never_runs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
                spool, "SPOOL_DIR", Path(directory) / "events"), patch.object(
                spool, "MAX_PENDING_FILES", 4), patch.object(
                spool.random, "randrange", return_value=1):
            for index in range(10):
                self.assertTrue(spool.publish(make_event(
                    "codex", "PreToolUse", "working", f"step {index}")))
            self.assertLessEqual(len(list(spool.SPOOL_DIR.glob("*.json"))), 4)

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
