"""Compact noisy tool lifecycle events while preserving important alerts."""

import time


class ProgressGate:
    def __init__(self, interval=3):
        self.interval = interval
        self.last_start = {}

    def show(self, event, mode="精简", filter_mode="全部类型", now=None):
        kind = event.get("kind")
        if filter_mode == "隐藏工作" and kind == "working":
            return False
        if filter_mode == "只看需处理" and kind not in {"attention", "error"}:
            return False
        if mode == "全部" or event.get("kind") in {"attention", "error", "success"}:
            return True
        name = event.get("event")
        if name == "PostToolUse":
            return False
        if name != "PreToolUse":
            return True
        now = time.monotonic() if now is None else now
        key = (event.get("agent"), event.get("session_id"), event.get("project"))
        previous = self.last_start.get(key, float("-inf"))
        if now - previous < self.interval:
            return False
        self.last_start[key] = now
        if len(self.last_start) > 256:
            self.last_start = {key: now}
        return True
