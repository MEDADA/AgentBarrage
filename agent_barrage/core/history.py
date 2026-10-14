"""Short-lived in-memory history used by the desktop display."""

import time
from collections import deque


class HistoryStore:
    def __init__(self, limit=200):
        self._items = deque(maxlen=limit)

    def add(self, source, message, kind, origin, private=False, open_url=""):
        self._items.append({
            "occurred_at": time.time(),
            "source": "智能体" if private else str(source)[:80],
            "message": "有一条新动态" if private else str(message)[:120],
            "kind": kind,
            "origin": origin,
            "open_url": "" if private else open_url,
        })

    def recent(self):
        return list(reversed(self._items))

    def clear(self):
        self._items.clear()

    def __len__(self):
        return len(self._items)
