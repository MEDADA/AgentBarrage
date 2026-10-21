import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_marquee.core.settings import sanitize_settings
from agent_marquee.notifications.wechat import extract_notifications, RecentNotifications, message_for
from agent_marquee.notifications.watcher import WeChatNotificationWatcher


def text(value):
    return {"role": "AXStaticText", "value": value, "children": []}


class WeChatNotificationsTest(unittest.TestCase):
    def test_extracts_only_wechat_groups_without_reading_other_apps(self):
        tree = {"role": "AXWindow", "children": [
            {"role": "AXGroup", "children": [text("微信"), text("张三"), text("今晚八点开会")]},
            {"role": "AXGroup", "children": [text("邮件"), text("微信"), text("其他应用") ]},
            {"role": "AXGroup", "children": [text("WeChat"), text("项目群"), text("会议纪要已发送")]},
        ]}
        found = extract_notifications(tree)
        self.assertEqual([(item["sender"], item["preview"]) for item in found],
                         [("张三", "今晚八点开会"), ("项目群", "会议纪要已发送")])

    def test_baseline_dedupes_and_expires(self):
        item = {"fingerprint": "first"}
        recent = RecentNotifications(retention=10)
        self.assertEqual(recent.new([item], now=0), [])
        self.assertEqual(recent.new([item], now=1), [])
        self.assertEqual(recent.new([{"fingerprint": "second"}], now=2), [{"fingerprint": "second"}])
        self.assertEqual(recent.new([item], now=12), [item])

    def test_preview_is_explicit_and_settings_default_off(self):
        item = {"sender": "张三", "preview": "私人消息", "fingerprint": "x"}
        self.assertEqual(message_for(item), "有新消息")
        self.assertEqual(message_for(item, True), "张三：私人消息")
        defaults = sanitize_settings({})
        self.assertFalse(defaults["wechat_enabled"])
        self.assertFalse(defaults["wechat_preview"])
        selected = sanitize_settings({"wechat_enabled": True, "wechat_preview": True,
                                      "wechat_ignored_chats": [" 工作群 ", "工作群", "家庭群"]})
        self.assertEqual(selected["wechat_ignored_chats"], ["工作群", "家庭群"])

    def test_watcher_sends_new_summary_then_opted_in_preview(self):
        sent = []
        snapshots = [
            [{"sender": "旧会话", "preview": "旧内容", "fingerprint": "old"}],
            [{"sender": "张三", "preview": "私人内容", "fingerprint": "new"}],
            [{"sender": "工作群", "preview": "忽略内容", "fingerprint": "ignored"},
             {"sender": "李四", "preview": "会议开始", "fingerprint": "latest"}],
        ]
        watcher = WeChatNotificationWatcher(publisher=sent.append, reader=lambda: snapshots.pop(0))
        with patch("agent_marquee.notifications.watcher.accessibility_trusted", return_value=True):
            watcher.poll_once()
            watcher.poll_once()
            watcher.configure(True, ["工作群"])
            watcher.poll_once()
        self.assertEqual([event["message"] for event in sent], ["有新消息", "李四：会议开始"])
        self.assertTrue(all(event["agent"] == "wechat" and event["project"] == "" for event in sent))

    def test_sequoia_style_stackingidentifier_with_chrome_first(self):
        tree = {"role": "AXWindow", "children": [
            {
                "role": "AXGroup",
                "subrole": "AXNotificationCenterBanner",
                "stackingidentifier": "com.tencent.xinWeChat",
                "children": [
                    text("关闭"),
                    text("张三"),
                    text("今晚一起吃饭吗"),
                ],
            },
        ]}
        found = extract_notifications(tree)
        self.assertEqual([(item["sender"], item["preview"]) for item in found],
                         [("张三", "今晚一起吃饭吗")])

    def test_finds_wechat_via_stackingidentifier_alone(self):
        tree = {
            "role": "AXGroup",
            "identifier": "com.tencent.xinwechat",
            "children": [text("项目群"), text("代码已合并")],
        }
        found = extract_notifications(tree)
        self.assertEqual([(item["sender"], item["preview"]) for item in found],
                         [("项目群", "代码已合并")])

    def test_app_marker_on_second_child_still_extracts(self):
        tree = {
            "role": "AXGroup",
            "children": [
                text("关闭"),
                text("微信"),
                text("李四"),
                text("明天见"),
            ],
        }
        found = extract_notifications(tree)
        self.assertEqual([(item["sender"], item["preview"]) for item in found],
                         [("李四", "明天见")])

    def test_watcher_records_last_error_without_crashing(self):
        def boom():
            raise RuntimeError("ax tree vanished")

        watcher = WeChatNotificationWatcher(publisher=lambda event: None, reader=boom)
        stop = threading.Event()

        def flip_after_first_wait(timeout=None):
            stop.set()
            return True

        stop.wait = flip_after_first_wait
        with patch("agent_marquee.notifications.watcher.accessibility_trusted", return_value=True):
            watcher._run(stop)
        self.assertEqual(watcher.error_count, 1)
        self.assertIn("ax tree vanished", watcher.last_error or "")


if __name__ == "__main__":
    unittest.main()
