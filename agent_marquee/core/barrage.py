"""Turn ordered observations and state decisions into bounded overlay prompts."""

from .event_v2 import as_display_event, LEGACY_EVENT_TYPES
from .progress import ProgressGate
from .traffic import PRIORITY, TrafficGate


class BarragePlanner:
    def __init__(self, ingestion, traffic=None, progress=None):
        self.ingestion = ingestion
        self.traffic = traffic or TrafficGate()
        self.progress = progress or ProgressGate()
        self.shown_attention = {}

    def plan(self, events, *, private=False, paused=False, progress_mode="精简",
             filter_mode="全部类型", now=None):
        """Apply state in arrival order, then order visible prompts by attention."""
        candidates = []
        for raw in events:
            item = self.ingestion.ingest(raw, private=private, received_at=now)
            if private or paused:
                continue
            # Events without work state still use the notification route.
            # Rejected duplicates and stale session updates stay silent.
            event_type = raw.get("event_type") or LEGACY_EVENT_TYPES.get(raw.get("event"))
            replayed = (self.ingestion.started_at is not None
                        and raw.get("occurred_at", 0) < self.ingestion.started_at)
            notification_only = (not raw.get("session_id")
                                 or event_type in {"session_started", "session_ended"}
                                 or replayed)
            if item is None and not notification_only:
                continue
            decision = None
            if item is not None:
                decision = self.ingestion.attention.decide([item], now=now)[0]
            candidates.append((raw, item, decision))

        if private or paused:
            return []
        current = {decision.work_key: decision for decision in self.ingestion.decisions(now=now)}
        ordered = []
        for index, (raw, item, decision) in enumerate(candidates):
            display = as_display_event(raw).copy()
            if decision is not None:
                latest = current.get(item.key)
                if latest is None or (decision.label, decision.priority) != (
                        latest.label, latest.priority):
                    continue
                if decision.priority <= 3:
                    signature = (decision.label, decision.confidence)
                    if self.shown_attention.get(item.key) == signature:
                        continue
                    self.shown_attention[item.key] = signature
                    display["message"] = decision.label
                    display["kind"] = "error" if decision.priority == 2 else "attention"
                    ordered.append((decision.priority, index, display))
                    continue
                self.shown_attention.pop(item.key, None)
            if (self.traffic.show(display, now=now)
                    and self.progress.show(display, progress_mode, filter_mode, now=now)):
                ordered.append((PRIORITY.get(display["kind"], 2) + 4, index, display))
        if len(self.shown_attention) > 512:
            active = set(self.ingestion.registry.items)
            self.shown_attention = {key: value for key, value in self.shown_attention.items()
                                    if key in active}
        return [display for _, _, display in sorted(ordered)]
