import unittest

from agent_barrage.core.traffic import TrafficGate, prioritize


def event(kind="working", message="正在工作", session="one", name="PreToolUse"):
    return {"agent": "codex", "session_id": session, "turn_id": "turn", "event": name,
            "kind": kind, "message": message}


class TrafficTest(unittest.TestCase):
    def test_duplicate_events_are_ignored_but_new_session_is_distinct(self):
        gate = TrafficGate()
        self.assertTrue(gate.show(event(), now=10))
        self.assertFalse(gate.show(event(), now=10.5))
        self.assertTrue(gate.show(event(session="two"), now=10.5))
        self.assertTrue(gate.show(event(), now=11.1))

    def test_burst_limits_working_but_never_hides_attention_or_errors(self):
        gate = TrafficGate(burst_limit=2)
        self.assertTrue(gate.show(event(message="one"), now=10))
        self.assertTrue(gate.show(event(message="two"), now=10.1))
        self.assertFalse(gate.show(event(message="three"), now=10.2))
        self.assertTrue(gate.show(event("attention", "需要批准"), now=10.2))
        self.assertTrue(gate.show(event("error", "执行失败"), now=10.2))
        self.assertTrue(gate.show(event(message="three"), now=15.1))

    def test_priority_retains_order_within_same_kind(self):
        items = [event(message="work"), event("success", "done"),
                 event("attention", "approve"), event("error", "failed")]
        self.assertEqual([item["message"] for item in prioritize(items)],
                         ["approve", "failed", "done", "work"])


if __name__ == "__main__":
    unittest.main()
