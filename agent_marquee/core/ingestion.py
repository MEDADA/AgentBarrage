"""Single state ingestion boundary, independent of barrage presentation gates."""

from .attention import AttentionEngine
from .event_v2 import valid_event_v2
from .events import valid_event
from .registry import SessionRegistry


class IngestionEngine:
    def __init__(self, registry=None, attention=None, *, started_at=None):
        self.registry = registry or SessionRegistry()
        self.attention = attention or AttentionEngine()
        self.started_at = started_at

    def ingest(self, event, *, private=False, received_at=None):
        if private:
            return None
        # Offline events can still become brief notifications, but cannot
        # establish a live task after this process has restarted.
        if self.started_at is not None and isinstance(event, dict):
            occurred_at = event.get("occurred_at")
            if type(occurred_at) in {int, float} and occurred_at < self.started_at:
                if not (valid_event(event) or valid_event_v2(event)):
                    raise ValueError("invalid canonical event")
                return None
        return self.registry.ingest(event, received_at=received_at)

    def decisions(self, *, private=False, paused=False, now=None):
        return self.attention.decide(
            self.registry.work_items(now=now), private=private, paused=paused, now=now)

    def clear(self):
        self.registry = SessionRegistry(
            stale_after=self.registry.stale_after,
            max_sessions=self.registry.max_sessions,
            max_work_items=self.registry.max_work_items,
            max_recent_events=self.registry.max_recent_events,
        )
