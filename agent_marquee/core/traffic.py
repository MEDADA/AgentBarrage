"""Bound duplicate and bursty routine events before they reach the overlay."""

import time
from collections import defaultdict, deque


PRIORITY = {"attention": 0, "error": 0, "success": 1, "working": 2}


def prioritize(events):
    """Keep arrival order within each priority while surfacing requests first."""
    return sorted(events, key=lambda event: PRIORITY.get(event.get("kind"), 2))


class TrafficGate:
    def __init__(self, duplicate_window=1.0, burst_window=5.0, burst_limit=8):
        self.duplicate_window = duplicate_window
        self.burst_window = burst_window
        self.burst_limit = burst_limit
        self.recent = {}
        self.routine_times = defaultdict(deque)

    def show(self, event, now=None):
        now = time.monotonic() if now is None else now
        kind = event.get("kind")
        source = (event.get("agent"), event.get("session_id"))
        fingerprint = (source, event.get("turn_id"), event.get("event"), kind,
                       event.get("message"), event.get("detail", ""))
        previous = self.recent.get(fingerprint)
        if previous is not None and now - previous < self.duplicate_window:
            return False
        if kind == "working":
            times = self.routine_times[source]
            while times and now - times[0] >= self.burst_window:
                times.popleft()
            if len(times) >= self.burst_limit:
                return False
            times.append(now)
        self.recent[fingerprint] = now
        if len(self.recent) > 512:
            self.recent = {key: seen for key, seen in self.recent.items()
                           if now - seen < self.duplicate_window}
        if len(self.routine_times) > 256:
            self.routine_times = defaultdict(deque, {
                key: times for key, times in self.routine_times.items()
                if times and now - times[-1] < self.burst_window})
        return True
