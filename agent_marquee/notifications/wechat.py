"""Normalize visible WeChat notification accessibility trees.

The parser accepts plain dictionaries so it can be tested without macOS or
access to a person's notifications. Raw preview text stays in memory only.
"""

import hashlib
import time

APP_NAMES = {"微信", "wechat"}
APP_IDENTIFIERS = ("com.tencent.xinwechat", "com.tencent.wechat")
CHROME_LABELS = {"关闭", "选项", "显示", "清除", "通知", "通知中心", "close", "options", "show", "clear"}


def _text(value):
    return " ".join(value.split())[:160] if isinstance(value, str) else ""


def _is_app_marker(value):
    text = _text(value).lower()
    return text in APP_NAMES or any(bundle in text for bundle in APP_IDENTIFIERS)


def _own_texts(node):
    return [_text(node.get(key)) for key in ("title", "value", "description") if _text(node.get(key))]


def _all_texts(node, limit=24):
    result = []
    stack = [node]
    while stack and len(result) < limit:
        current = stack.pop()
        for value in _own_texts(current):
            if value not in result:
                result.append(value)
        stack.extend(reversed(current.get("children", [])[:32]))
    return result


def extract_notifications(tree):
    """Find the smallest groups that visibly identify themselves as WeChat."""
    found = []

    def visit(node, depth=0):
        if depth > 9:
            return False
        child_found = False
        for child in node.get("children", [])[:32]:
            if visit(child, depth + 1):
                child_found = True
        if child_found:
            return True
        immediate = _own_texts(node) + [_text(node.get("identifier"))]
        for child in node.get("children", [])[:4]:
            label = _own_texts(child) + [_text(child.get("identifier"))]
            if any(label):
                immediate.extend(label)
                break
        identified = any(_is_app_marker(value) for value in immediate)
        if not identified:
            return False
        texts = [value for value in _all_texts(node) if not _is_app_marker(value)
                 and value.lower() not in CHROME_LABELS]
        if not texts:
            return False
        sender = texts[0]
        preview = texts[1] if len(texts) > 1 else ""
        fingerprint = hashlib.sha256("\x1f".join((sender, preview)).encode("utf-8")).hexdigest()
        found.append({"sender": sender, "preview": preview, "fingerprint": fingerprint})
        return True

    visit(tree)
    return found


class RecentNotifications:
    """Skip already visible notifications and short-term duplicates."""

    def __init__(self, retention=30):
        self.retention = retention
        self.seen = {}
        self.started = False

    def new(self, notifications, now=None):
        now = time.monotonic() if now is None else now
        self.seen = {key: value for key, value in self.seen.items() if now - value < self.retention}
        fresh = []
        for item in notifications:
            key = item["fingerprint"]
            if key not in self.seen and self.started:
                fresh.append(item)
            self.seen[key] = now
        self.started = True
        return fresh


def message_for(notification, preview_enabled=False):
    if not preview_enabled:
        return "有新消息"
    sender = _text(notification.get("sender"))[:24]
    preview = _text(notification.get("preview"))[:64]
    if sender and preview:
        return f"{sender}：{preview}"[:120]
    return f"来自 {sender} 的新消息" if sender else "有新消息"
