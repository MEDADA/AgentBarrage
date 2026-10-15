import json
import http.client
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_marquee.adapters.codex import normalize
from agent_marquee.adapters.claude_code import normalize as normalize_claude
from agent_marquee.adapters.codebuddy import normalize as normalize_codebuddy
from agent_marquee.core.events import make_event, valid_event
from agent_marquee.core.history import HistoryStore
from agent_marquee.core.progress import ProgressGate
from agent_marquee.core.settings import load_settings, save_settings
from agent_marquee.core.sources import SourceRegistry, add_source, load_sources, remove_source, set_source_enabled, set_source_icon
from agent_marquee.bridge import make_handler, load_or_create_token
from agent_marquee.core import spool
from agent_marquee.core import migration
from agent_marquee.install import EVENTS, CONFIG_PATHS, command_for, is_our_handler, update_config, atomic_save, integration_status, apply_agent
import agent_marquee.install as install_module


class HookBridgeTest(unittest.TestCase):
    def test_sensitive_fields_are_not_forwarded(self):
        event = normalize({
            "hook_event_name": "PostToolUse",
            "session_id": "session-1",
            "cwd": "/private/work/Example",
            "tool_name": "Bash",
            "tool_input": {"command": "echo secret-token"},
            "tool_response": {"exit_code": 1, "output": "secret-token"},
        })
        text = json.dumps(event, ensure_ascii=False)
        self.assertEqual(event["kind"], "error")
        self.assertTrue(valid_event(event))
        self.assertNotIn("secret-token", text)
        self.assertNotIn("/private/work", text)

    def test_partial_detail_is_allowlisted_and_short(self):
        event = normalize({
            "hook_event_name": "PreToolUse", "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: /private/work/Example/app.py\n+secret-token\n*** End Patch"},
        })
        self.assertEqual(event["detail"], "app.py")
        self.assertNotIn("secret-token", json.dumps(event))
        command = normalize({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                             "tool_input": {"command": "python3 -m unittest secret-token"}})
        self.assertEqual(command["detail"], "python3")
        unsafe = normalize({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": "SECRET=abc python3 test.py"}})
        self.assertNotIn("detail", unsafe)

    def test_compact_progress_keeps_attention_and_error(self):
        gate = ProgressGate(interval=3)
        start = make_event("codex", "PreToolUse", "working", "正在运行命令", "Demo", "session")
        end = make_event("codex", "PostToolUse", "working", "运行命令已结束", "Demo", "session")
        error = make_event("codex", "PostToolUse", "error", "运行命令失败", "Demo", "session")
        self.assertTrue(gate.show(start, now=10))
        self.assertFalse(gate.show(start, now=11))
        self.assertFalse(gate.show(end, now=12))
        self.assertTrue(gate.show(error, now=12))
        self.assertTrue(gate.show(start, mode="全部", now=12))
        self.assertTrue(gate.show(start, now=14))
        self.assertFalse(gate.show(start, filter_mode="隐藏工作", now=15))
        self.assertFalse(gate.show(make_event("codex", "Stop", "success", "完成"), filter_mode="只看需处理"))
        self.assertTrue(gate.show(error, filter_mode="只看需处理", now=15))

    def test_other_adapters_share_schema(self):
        payload = {"hook_event_name": "Stop", "cwd": "/work/Sample", "session_id": "abc"}
        self.assertTrue(valid_event(normalize_claude(payload)))
        self.assertTrue(valid_event(normalize_codebuddy(payload)))

    def test_custom_agent_uses_same_protocol(self):
        event = make_event("my-agent", "custom", "success", "Done", "Sample")
        self.assertTrue(valid_event(event))

    def test_event_validation_rejects_invalid_timestamp_and_detail(self):
        event = make_event("my-agent", "custom", "success", "Done", "Sample")
        self.assertFalse(valid_event({**event, "occurred_at": "tomorrow"}))
        self.assertFalse(valid_event({**event, "detail": "x" * 49}))

    def test_history_is_bounded_and_private(self):
        history = HistoryStore(limit=2)
        history.add("CODEX · Secret", "private work", "working", "真实", private=True)
        self.assertEqual(history.recent()[0]["source"], "智能体")
        self.assertEqual(history.recent()[0]["message"], "有一条新动态")
        history.add("Claude", "finished", "success", "真实")
        history.add("CodeBuddy", "finished", "success", "真实")
        self.assertEqual(len(history), 2)
        history.clear()
        self.assertEqual(len(history), 0)

    def test_file_transport(self):
        event = normalize({"hook_event_name": "PermissionRequest", "cwd": "/work/Sample"})
        previous = spool.SPOOL_DIR
        with tempfile.TemporaryDirectory() as directory:
            spool.SPOOL_DIR = Path(directory) / "events"
            try:
                self.assertTrue(spool.publish(event))
                self.assertIn(event, spool.drain())
            finally:
                spool.SPOOL_DIR = previous

    def test_install_is_idempotent_and_preserves_existing_hooks(self):
        existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]}}
        once = update_config(existing, "codex")
        snapshot = json.dumps(once, sort_keys=True)
        twice = update_config(once, "codex")
        self.assertEqual(snapshot, json.dumps(twice, sort_keys=True))
        self.assertEqual(len(twice["hooks"]), len(EVENTS["codex"]))
        removed = update_config(twice, "codex", uninstall=True)
        self.assertEqual(removed["hooks"]["Stop"][0]["hooks"][0]["command"], "echo existing")
        self.assertEqual(len(removed["hooks"]), 1)

    def test_each_agent_install_preserves_unrelated_settings(self):
        for agent in ("claude-code", "codebuddy"):
            config = {"theme": "dark", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo keep"}]}]}}
            installed = update_config(config, agent)
            self.assertEqual(installed["theme"], "dark")
            self.assertEqual(installed["hooks"]["Stop"][0]["hooks"][0]["command"], "echo keep")
            removed = update_config(installed, agent, uninstall=True)
            self.assertEqual(removed["hooks"]["Stop"][0]["hooks"][0]["command"], "echo keep")

    def test_uninstall_matches_only_our_exact_command(self):
        self.assertTrue(is_our_handler({"command": command_for("codex")}, "codex"))
        self.assertFalse(is_our_handler({"command": "echo agent-marquee-emit --adapter codex"}, "codex"))
        self.assertFalse(is_our_handler({"command": command_for("claude-code")}, "codex"))
        self.assertFalse(is_our_handler({"command": "unterminated ' quote"}, "codex"))
        self.assertTrue(is_our_handler({"command": "/usr/bin/env python3 /old/bin/agent-barrage-emit --adapter codex"}, "codex"))
        self.assertTrue(is_our_handler({"command": "/usr/bin/python3 -m agent_barrage.emit --adapter codex"}, "codex"))
        self.assertTrue(is_our_handler({"command": "/Applications/AgentBarrage.app/Contents/MacOS/AgentBarrage --hook-adapter codex"}, "codex"))
        with patch.object(install_module, "EMITTER_PATH", Path("/definitely/missing/agent-marquee-emit")):
            packaged = command_for("codex")
            self.assertIn("-m agent_marquee.emit", packaged)
            self.assertTrue(is_our_handler({"command": packaged}, "codex"))
        with tempfile.TemporaryDirectory() as directory:
            fake_script = Path(directory) / "bin" / "agent-marquee-emit"
            fake_script.parent.mkdir()
            fake_script.write_text("", encoding="utf-8")
            with patch.object(install_module, "EMITTER_PATH", fake_script):
                self.assertIn("-m agent_marquee.emit", command_for("codex"))

    def test_installer_rejects_symlinked_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "real.json"
            target.write_text("{}", encoding="utf-8")
            link = Path(directory) / "settings.json"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                atomic_save(link, "{}\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_integration_status_and_independent_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = CONFIG_PATHS["codex"]
            CONFIG_PATHS["codex"] = Path(directory) / "hooks.json"
            try:
                self.assertEqual(integration_status("codex"), (0, len(EVENTS["codex"])))
                apply_agent("codex")
                self.assertEqual(integration_status("codex"), (len(EVENTS["codex"]), len(EVENTS["codex"])))
                apply_agent("codex", uninstall=True)
                self.assertEqual(integration_status("codex"), (0, len(EVENTS["codex"])))
            finally:
                CONFIG_PATHS["codex"] = previous

    def test_settings_migrate_from_demo_to_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "demo.json"
            current = Path(directory) / "user" / "settings.json"
            legacy.write_text('{"style":"纯文字","progress":"全部","font_size":999}', encoding="utf-8")
            settings = load_settings(current, legacy)
            self.assertEqual(settings["style"], "纯文字")
            self.assertEqual(settings["font_family"], "苹方")
            self.assertEqual(settings["font_size"], 16)
            self.assertEqual(settings["text_color"], "#FFFFFF")
            self.assertFalse(settings["outline_enabled"])
            self.assertEqual(settings["outline_color"], "#141A26")
            self.assertEqual(settings["outline_width"], 0.5)
            self.assertEqual(settings["motion"], "滚动")
            self.assertTrue(settings["show_icons"])
            self.assertEqual(settings["event_filter"], "全部类型")
            self.assertTrue(current.exists())
            settings["progress"] = "精简"
            settings["text_color"] = "#141A26"
            settings["outline_enabled"] = True
            settings["outline_color"] = "#F0A070"
            settings["outline_width"] = 1.5
            settings["font_family"] = "宋体"
            settings["motion"] = "固定停留"
            settings["density"] = 4
            settings["show_icons"] = False
            save_settings(settings, current)
            self.assertEqual(load_settings(current, legacy)["progress"], "精简")
            self.assertEqual(load_settings(current, legacy)["text_color"], "#141A26")
            self.assertTrue(load_settings(current, legacy)["outline_enabled"])
            self.assertEqual(load_settings(current, legacy)["outline_color"], "#F0A070")
            self.assertEqual(load_settings(current, legacy)["outline_width"], 1.5)
            self.assertEqual(load_settings(current, legacy)["font_family"], "宋体")
            self.assertEqual(load_settings(current, legacy)["motion"], "固定停留")
            self.assertEqual(load_settings(current, legacy)["density"], 4)
            self.assertFalse(load_settings(current, legacy)["show_icons"])
            current.write_text('{"text_color":"暖黄"}', encoding="utf-8")
            self.assertEqual(load_settings(current, legacy)["text_color"], "#FFE073")
            current.write_text('{"outline_enabled":"yes","outline_color":"invalid","outline_width":99,"font_family":"unknown"}', encoding="utf-8")
            invalid = load_settings(current, legacy)
            self.assertFalse(invalid["outline_enabled"])
            self.assertEqual(invalid["outline_color"], "#141A26")
            self.assertEqual(invalid["outline_width"], 0.5)
            self.assertEqual(invalid["font_family"], "苹方")

    def test_custom_sources_are_named_and_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            add_source("my-chat", "  我的   AI 对话  ", path)
            self.assertEqual(load_sources(path), [{"id": "my-chat", "name": "我的 AI 对话", "enabled": True, "icon": None}])
            registry = SourceRegistry(path)
            self.assertEqual(registry.display_name("my-chat"), "我的 AI 对话")
            self.assertTrue(registry.is_enabled("my-chat"))
            image = Path(directory) / "chosen.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            set_source_icon("my-chat", image, path)
            registry.refresh(force=True)
            self.assertEqual(registry.icon_path("my-chat").read_bytes(), image.read_bytes())
            set_source_enabled("my-chat", False, path)
            registry.refresh(force=True)
            self.assertFalse(registry.is_enabled("my-chat"))
            with self.assertRaises(ValueError):
                add_source("my-chat", "重复", path)
            with self.assertRaises(ValueError):
                add_source("codex", "覆盖内置来源", path)
            remove_source("my-chat", path)
            registry.refresh(force=True)
            self.assertIsNone(registry.display_name("my-chat"))
            self.assertFalse((path.parent / "icons" / "my-chat.png").exists())
            path.write_text('{"version":1,"sources":[{"id":"old-tool","name":"旧工具"}]}', encoding="utf-8")
            self.assertTrue(load_sources(path)[0]["enabled"])
            self.assertIsNone(load_sources(path)[0]["icon"])

    def test_local_bridge_requires_token_and_registered_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            add_source("my-chat", "我的 AI 对话", path)
            registry = SourceRegistry(path)
            events = []
            try:
                server = ThreadingHTTPServer(("127.0.0.1", 0),
                                             make_handler("test-secret", registry, lambda event: events.append(event) or True))
            except PermissionError:
                self.skipTest("local socket binding is disabled in this sandbox")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                body = json.dumps({"agent": "my-chat", "kind": "success", "message": "回答完成",
                                   "detail": "摘要片段", "open_url": "https://example.com/task/123"})
                connection.request("POST", "/v1/events", body, {"Content-Type": "application/json"})
                self.assertEqual(connection.getresponse().status, 401)
                connection.request("POST", "/v1/events", body,
                                   {"Content-Type": "application/json", "Authorization": "Bearer test-secret"})
                self.assertEqual(connection.getresponse().status, 202)
                self.assertEqual(events[0]["agent"], "my-chat")
                self.assertEqual(events[0]["detail"], "摘要片段")
                self.assertEqual(events[0]["open_url"], "https://example.com/task/123")
                set_source_enabled("my-chat", False, path)
                connection.request("POST", "/v1/events", body,
                                   {"Content-Type": "application/json", "Authorization": "Bearer test-secret"})
                self.assertEqual(connection.getresponse().status, 403)
                set_source_enabled("my-chat", True, path)
                other = json.dumps({"agent": "unknown", "kind": "success", "message": "完成"})
                connection.request("POST", "/v1/events", other,
                                   {"Content-Type": "application/json", "Authorization": "Bearer test-secret"})
                self.assertEqual(connection.getresponse().status, 422)
                unsafe_link = json.dumps({"agent": "my-chat", "kind": "success", "message": "完成",
                                          "open_url": "file:///etc/passwd"})
                connection.request("POST", "/v1/events", unsafe_link,
                                   {"Content-Type": "application/json", "Authorization": "Bearer test-secret"})
                self.assertEqual(connection.getresponse().status, 422)
                malformed = json.dumps({"agent": "my-chat", "kind": [], "message": "完成"})
                connection.request("POST", "/v1/events", malformed,
                                   {"Content-Type": "application/json", "Authorization": "Bearer test-secret"})
                self.assertEqual(connection.getresponse().status, 422)
                self.assertEqual(len(events), 1)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_bridge_token_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-token"
            token = load_or_create_token(path)
            self.assertEqual(token, load_or_create_token(path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


    def test_rename_migrates_data_without_overwriting_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "AgentBarrage"
            new = Path(directory) / "AgentMarquee"
            (old / "icons").mkdir(parents=True)
            (old / "settings.json").write_text('{"style":"纯文字"}', encoding="utf-8")
            (old / "sources.json").write_text('{"version":1,"sources":[]}', encoding="utf-8")
            (old / "bridge-token").write_text("old-secret", encoding="ascii")
            (old / "icons" / "custom.png").write_bytes(b"image")
            new.mkdir()
            (new / "settings.json").write_text("newer", encoding="utf-8")
            with patch.object(migration, "LEGACY_DATA_DIR", old), patch.object(migration, "DATA_DIR", new):
                migration.migrate_user_data()
                migration.migrate_user_data()
            self.assertEqual((new / "settings.json").read_text(), "newer")
            self.assertEqual((new / "sources.json").read_text(), '{"version":1,"sources":[]}')
            self.assertEqual((new / "bridge-token").read_text(), "old-secret")
            self.assertEqual((new / "icons" / "custom.png").read_bytes(), b"image")


if __name__ == "__main__":
    unittest.main()
