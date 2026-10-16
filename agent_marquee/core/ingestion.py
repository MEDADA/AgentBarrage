"""Single state ingestion boundary, independent of barrage presentation gates."""

from .attention import AttentionEngine
from .registry import SessionRegistry


class IngestionEngine:
    def __init__(self, registry=None, attention=None):
        self.registry = registry or SessionRegistry()
        self.attention = attention or AttentionEngine()

    def ingest(self, event, *, private=False, received_at=None):
        if private:
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
