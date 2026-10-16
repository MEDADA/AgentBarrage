"""The canonical envelope preserves observations without inventing outcomes."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_marquee.core.event_v2 import as_display_event, from_v1, make_event_v2, valid_event_v2
from agent_marquee.core.events import make_event
from agent_marquee.core import spool
from agent_marquee.core.traffic import prioritize


class EventV2Test(unittest.TestCase):
    def test_constructs_and_validates_observed_event(self):
        event = make_event_v2(
            "codex", "tool_started", "正在运行命令", project="Demo",
            session_id="s1", turn_id="t1", source_instance="local",
            sequence=7,
        )
        self.assertEqual(event["version"], 2)
        self.assertEqual(event["event_type"], "tool_started")
        self.assertTrue(event["event_id"])
        self.assertTrue(valid_event_v2(event))

    def test_legacy_stop_is_observation_not_completion(self):
        legacy = make_event("codex", "Stop", "success", "任务已完成", "Demo", "s1", "t1")
        event = from_v1(legacy)
        self.assertEqual(event["event_type"], "turn_stop_observed")
        self.assertNotIn("lifecycle_state", event)
        self.assertEqual(event["presentation_kind"], "success")
        self.assertEqual(event["session_id"], "s1")
        self.assertEqual(from_v1(legacy)["event_id"], event["event_id"])

    def test_legacy_kind_never_creates_lifecycle_outcome(self):
        legacy = make_event("my-agent", "custom", "success", "已完成", "Demo")
        event = from_v1(legacy)
        self.assertEqual(event["event_type"], "custom")
        self.assertNotIn("lifecycle_state", event)
        self.assertEqual(event["session_id"], "")

    def test_validation_rejects_unsafe_shape(self):
        good = make_event_v2("codex", "approval_requested", "可能需要批准", session_id="s1")
        self.assertFalse(valid_event_v2({**good, "event_id": ""}))
        self.assertFalse(valid_event_v2({**good, "event_type": "completed"}))
        self.assertFalse(valid_event_v2({**good, "sequence": True}))
        self.assertFalse(valid_event_v2({**good, "occurred_at": float("nan")}))
        self.assertFalse(valid_event_v2({**good, "open_url": "file:///private/data"}))
        self.assertFalse(valid_event_v2({**good, "summary": "x" * 121}))
        self.assertFalse(valid_event_v2({**good, "event_type": []}))
        self.assertFalse(valid_event_v2({**good, "presentation_kind": []}))
        self.assertFalse(valid_event_v2({**good, "session_id": "bad\nidentity"}))
        self.assertFalse(valid_event_v2({key: value for key, value in good.items() if key != "summary"}))

    def test_constructor_does_not_stringify_raw_payload(self):
        with self.assertRaises(ValueError):
            make_event_v2("codex", "tool_started", {"tool_input": "private"})

    def test_legacy_conversion_keeps_safe_fields_only(self):
        legacy = make_event("codex", "PreToolUse", "working", "正在使用工具", "/secret/Demo", "s1")
        legacy["tool_input"] = {"command": "secret-token"}
        event = from_v1(legacy)
        self.assertTrue(valid_event_v2(event))
        self.assertNotIn("secret-token", json.dumps(event))
        self.assertNotIn("/secret", json.dumps(event))

    def test_v2_survives_local_transport_and_has_display_view(self):
        event = make_event_v2(
            "codex", "tool_started", "正在运行命令", project="Demo",
            session_id="s1", turn_id="t1", detail="python3",
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(spool, "SPOOL_DIR", Path(directory)):
            self.assertTrue(spool.publish(event))
            drained = spool.drain()
        self.assertEqual(drained, [event])
        shown = as_display_event(drained[0])
        self.assertEqual(shown["kind"], "working")
        self.assertEqual(shown["message"], "正在运行命令")
        self.assertEqual(shown["project"], "Demo")
        self.assertEqual(shown["detail"], "python3")
        self.assertEqual(shown["session_id"], "s1")

    def test_v2_attention_keeps_existing_priority(self):
        working = make_event_v2("codex", "tool_started", "正在使用工具")
        approval = make_event_v2(
            "codex", "approval_requested", "可能需要批准",
            presentation_kind="attention",
        )
        self.assertEqual(prioritize([working, approval]), [approval, working])


if __name__ == "__main__":
    unittest.main()
