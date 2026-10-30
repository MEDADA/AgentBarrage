"""Bounded in-memory session registry fed by v1 or v2 events."""

import time
from collections import deque
from dataclasses import replace

from .event_v2 import from_v1, valid_event_v2
from .reducer import TERMINAL, WorkSnapshot, reduce_work


class SessionRegistry:
    def __init__(self, *, stale_after=600, max_sessions=256,
                 max_work_items=512, max_recent_events=2048):
        self.stale_after = stale_after
        self.max_sessions = max_sessions
        self.max_work_items = max_work_items
        self.max_recent_events = max_recent_events
        self.sessions = {}
        self.items = {}
        self.seen = set()
        self.recent_ids = deque()

    def session_status(self, agent, source_instance, session_id):
        return self.sessions.get((agent, source_instance, session_id), ("unknown", 0))[0]

    def ingest(self, raw_event, *, received_at=None):
        if not isinstance(raw_event, dict):
            raise ValueError("invalid canonical event")
        event = from_v1(raw_event) if raw_event.get("version") == 1 else raw_event
        if not valid_event_v2(event):
            raise ValueError("invalid canonical event")
        if not event.get("session_id"):
            return None
        source = (event["agent"], event.get("source_instance", ""))
        dedup_key = (*source, event["event_id"])
        if dedup_key in self.seen:
            return None
        self.seen.add(dedup_key)
        self.recent_ids.append(dedup_key)
        while len(self.recent_ids) > self.max_recent_events:
            self.seen.discard(self.recent_ids.popleft())

        now = time.time() if received_at is None else received_at
        session_key = (*source, event["session_id"])
        if (self.session_status(*session_key) == "ended"
                and event["event_type"] != "session_started"):
            return None
        if event["event_type"] == "session_ended":
            self.sessions[session_key] = ("ended", now)
            for key, item in tuple(self.items.items()):
                if key[:3] == session_key and item.state not in TERMINAL:
                    self.items[key] = replace(item, state="unknown", updated_at=now,
                                              attention="", attention_confidence="")
            self._bound()
            return None

        if event["event_type"] == "session_started":
            if self.session_status(*session_key) == "ended":
                for key in tuple(self.items):
                    if key[:3] == session_key:
                        self.items.pop(key)
            self.sessions[session_key] = ("open", now)
            self._bound()
            return None

        self.sessions[session_key] = ("open", now)

        work_id = event.get("task_id") or event.get("turn_id") or "__session__"
        key = (*session_key, work_id)
        previous = self.items.get(key)
        sequence = event.get("sequence")
        if (previous is not None and sequence is not None
                and previous.last_sequence is not None and sequence <= previous.last_sequence):
            return None
        item = reduce_work(previous, event, now, key)
        self.items[key] = item
        self._bound()
        return item

    def work_items(self, *, now=None):
        now = time.time() if now is None else now
        return [replace(item, health="stale" if now - item.updated_at > self.stale_after
                        and item.state not in TERMINAL else "fresh")
                for item in self.items.values()]

    def _bound(self):
        while len(self.sessions) > self.max_sessions:
            oldest = min(self.sessions, key=lambda key: self.sessions[key][1])
            self.sessions.pop(oldest)
            for key in tuple(self.items):
                if key[:3] == oldest:
                    self.items.pop(key)
        while len(self.items) > self.max_work_items:
            oldest = min(self.items, key=lambda key: self.items[key].updated_at)
            self.items.pop(oldest)
