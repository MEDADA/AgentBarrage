"""Optional background reader for visible desktop notifications."""

import threading

from agent_marquee.core.events import make_event
from agent_marquee.core.spool import publish

from .macos_ax import accessibility_trusted, visible_wechat_notifications
from .wechat import RecentNotifications, message_for


class WeChatNotificationWatcher:
    def __init__(self, publisher=publish, reader=visible_wechat_notifications):
        self.publisher = publisher
        self.reader = reader
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.preview_enabled = False
        self.ignored_chats = set()
        self.thread = None
        self.recent = RecentNotifications()

    def configure(self, preview_enabled=False, ignored_chats=()):
        with self.lock:
            self.preview_enabled = bool(preview_enabled)
            self.ignored_chats = {name.strip() for name in ignored_chats if isinstance(name, str) and name.strip()}

    def start(self):
        if self.thread is None or not self.thread.is_alive() or self.stop_event.is_set():
            self.stop_event = threading.Event()
            self.recent = RecentNotifications()
            self.thread = threading.Thread(target=self._run, args=(self.stop_event,),
                                           name="wechat-notifications", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()

    def poll_once(self, stop_event=None):
        if not accessibility_trusted():
            return
        fresh = self.recent.new(self.reader())
        with self.lock:
            preview = self.preview_enabled
            ignored = self.ignored_chats.copy()
        for item in fresh[:4]:
            if stop_event is not None and stop_event.is_set():
                break
            if item["sender"] in ignored:
                continue
            event = make_event("wechat", "notification", "attention",
                               message_for(item, preview), turn_id=item["fingerprint"])
            event["project"] = ""
            self.publisher(event)

    def _run(self, stop_event):
        while not stop_event.is_set():
            try:
                self.poll_once(stop_event)
            except Exception:
                pass  # Notification Center may restart or change its AX tree.
            stop_event.wait(1.5)
