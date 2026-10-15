"""Native macOS overlay and control window."""

import argparse
import random
import shlex
import sys
from datetime import datetime
from pathlib import Path
import objc
from AppKit import *
from Foundation import NSObject, NSString, NSTimer, NSURL
from agent_marquee.core.spool import drain, ensure_spool
from agent_marquee.core.history import HistoryStore
from agent_marquee.core.progress import ProgressGate
from agent_marquee.core.traffic import TrafficGate, prioritize
from agent_marquee.core.settings import DEFAULT_SETTINGS, load_settings, save_settings
from agent_marquee.core.sources import SourceRegistry, add_source, load_sources, remove_source, set_source_enabled, set_source_icon
from agent_marquee.core.events import make_event
from agent_marquee.core.spool import publish
from agent_marquee.install import CONFIG_PATHS, apply_agent, integration_status
from agent_marquee.notifications.macos_ax import accessibility_trusted
from agent_marquee.notifications.watcher import WeChatNotificationWatcher
from .icons import IconResolver

INTEGRATIONS = [
    ("codex", "Codex"), ("claude-code", "Claude Code"), ("codebuddy", "CodeBuddy Code"),
]

PALETTE = {
    "working": (0.30, 0.78, 1.00),
    "success": (0.42, 0.91, 0.66),
    "attention": (1.00, 0.72, 0.34),
    "error": (1.00, 0.43, 0.47),
}
def tint(kind, alpha=1):
    red, green, blue = PALETTE[kind]
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(red, green, blue, alpha)


def color_from_hex(value, alpha=1):
    red, green, blue = (int(value[index:index + 2], 16) / 255 for index in (1, 3, 5))
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(red, green, blue, alpha)


def color_to_hex(color):
    rgb = color.colorUsingColorSpaceName_(NSCalibratedRGBColorSpace)
    if rgb is None:
        return "#FFFFFF"
    return "#{:02X}{:02X}{:02X}".format(
        round(rgb.redComponent() * 255), round(rgb.greenComponent() * 255), round(rgb.blueComponent() * 255))


def system_reduce_motion():
    method = getattr(NSWorkspace.sharedWorkspace(), "accessibilityDisplayShouldReduceMotion", None)
    return bool(method()) if callable(method) else False


def status_icon():
    """A small motion bubble; template coloring follows the macOS menu bar."""
    icon = NSImage.alloc().initWithSize_(NSMakeSize(20, 18))
    icon.lockFocus()
    NSColor.blackColor().setStroke()
    NSColor.blackColor().setFill()
    bubble = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(6, 3, 13, 12), 4, 4)
    bubble.setLineWidth_(1.6)
    bubble.stroke()
    for x, y, width in ((0, 10.5, 4.5), (1.5, 6.5, 3)):
        streak = NSBezierPath.bezierPath()
        streak.moveToPoint_(NSMakePoint(x, y))
        streak.lineToPoint_(NSMakePoint(x + width, y))
        streak.setLineWidth_(1.6)
        streak.stroke()
    for x in (9, 12, 15):
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, 8, 1.6, 1.6)).fill()
    icon.unlockFocus()
    icon.setTemplate_(True)
    return icon


def typeface(size, weight=NSFontWeightSemibold):
    return NSFont.systemFontOfSize_weight_(size, weight)


def barrage_font(size, role, family):
    weights = {"source": NSFontWeightSemibold, "project": NSFontWeightRegular,
               "message": NSFontWeightMedium}
    names = {
        "苹方": ("PingFangSC-Regular", "PingFangSC-Medium", "PingFangSC-Semibold"),
        "冬青": ("HiraginoSansGB-W3", "HiraginoSansGB-W3", "HiraginoSansGB-W6"),
        "宋体": ("STSongti-SC-Regular", "STSongti-SC-Regular", "STSongti-SC-Bold"),
        "华文黑体": ("STHeitiSC-Light", "STHeitiSC-Medium", "STHeitiSC-Medium"),
    }
    if family in names:
        index = {"project": 0, "message": 1, "source": 2}[role]
        font = NSFont.fontWithName_size_(names[family][index], size)
        if font is not None:
            return font
    return typeface(size, weights[role])


def measure(text, face):
    return NSString.stringWithString_(text).sizeWithAttributes_({NSFontAttributeName: face}).width


def fit_text(value, face, limit):
    if measure(value, face) <= limit:
        return value
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(value[:middle] + "…", face) <= limit:
            low = middle
        else:
            high = middle - 1
    return value[:low] + "…"


def draw_barrage_text(value, point, face, foreground, settings, opacity):
    text = NSString.stringWithString_(value)
    if settings["outline_enabled"]:
        # A positive width draws only the stroke. Cover its inner half with a
        # second fill pass, leaving the requested width outside the glyph.
        text.drawAtPoint_withAttributes_(point, {
            NSFontAttributeName: face,
            NSStrokeColorAttributeName: color_from_hex(settings["outline_color"], opacity),
            NSStrokeWidthAttributeName: 200 * settings["outline_width"] / face.pointSize(),
        })
    text.drawAtPoint_withAttributes_(point, {
        NSFontAttributeName: face, NSForegroundColorAttributeName: foreground,
    })


class Canvas(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(Canvas, self).initWithFrame_(frame)
        if self:
            self.items, self.lane, self.paused, self.privacy = [], 0, False, False
            self.settings = DEFAULT_SETTINGS.copy()
            self.reduce_motion = False
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def emit(self, source, message, kind, icon=None):
        if self.privacy:
            source = "智能体"
            icon = None
        message = "有一条新动态" if self.privacy else message
        size = int(self.settings["font_size"])
        style = self.settings["style"]
        if style == "纯文字" or not self.settings["show_icons"]:
            icon = None
        source, separator, project = source.partition(" · ")
        if not separator:
            project = ""
        icon_offset = 24 if icon is not None else 0
        padding = 13 if style != "纯文字" else 0
        gap = 10
        max_width = max(240, self.bounds().size.width - 48)
        family = self.settings["font_family"]
        source_face = barrage_font(size - 3, "source", family)
        project_face = barrage_font(size - 4, "project", family)
        message_face = barrage_font(size, "message", family)
        source = fit_text(source, source_face, max(58, max_width * 0.18))
        if project:
            project = fit_text(project, project_face, max(70, max_width * 0.25))
        content_width = max_width - 2 * padding - icon_offset - gap * (2 if project else 1)
        message = fit_text(message, message_face,
                           max(24, content_width - measure(source, source_face) - measure(project, project_face)))
        width = (2 * padding + icon_offset + measure(source, source_face) +
                 measure(project, project_face) + measure(message, message_face) +
                 gap * (2 if project else 1))
        gap = int(self.settings["spacing"])
        region = self.settings["region"]
        height = self.bounds().size.height
        area = height * float(self.settings["coverage"])
        lane_count = max(1, min(int(self.settings["density"]), int(area / gap)))
        base = {"顶部": 72, "中部": max(72, (height - lane_count * gap) / 2),
                "底部": max(72, height - lane_count * gap - 80)}[region]
        y = base + (self.lane % lane_count) * gap
        self.lane += 1
        fixed = self.settings["motion"] == "固定停留" or self.reduce_motion
        x = (self.bounds().size.width - width) / 2 if fixed else self.bounds().size.width + 24
        speed = 0 if fixed else (1.25 if kind == "attention" else random.uniform(1.8, 2.2)) * float(self.settings["speed"])
        remaining = round(float(self.settings["fixed_duration"]) * 60) if fixed else None
        if len(self.items) >= int(self.settings["density"]):
            drop_index = next((index for index, item in enumerate(self.items) if item[5] == "working"), None)
            if drop_index is None and kind == "working":
                return
            self.items.pop(drop_index if drop_index is not None else 0)
        self.items.append([x, y, width, source, message, kind, speed, icon, remaining, project])
        self.setNeedsDisplay_(True)

    @objc.python_method
    def tick(self):
        if self.paused:
            return
        had_items = bool(self.items)
        for item in self.items:
            item[0] -= item[6]
            if item[8] is not None:
                item[8] -= 1
        self.items = [item for item in self.items if item[0] + item[2] > 0 and (item[8] is None or item[8] > 0)]
        if had_items:
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        for x, y, width, source, message, kind, speed, icon, remaining, project in self.items:
            size = int(self.settings["font_size"])
            pill_height = size + 18
            style = self.settings["style"]
            opacity = float(self.settings["opacity"])
            if style != "纯文字":
                bubble = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(x, y, width, pill_height), pill_height / 2, pill_height / 2)
                background_alpha = opacity if style == "胶囊" else opacity * 0.50
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.05, 0.075, 0.12, background_alpha).setFill()
                bubble.fill()
                if style == "胶囊":
                    tint(kind, opacity * 0.8).setStroke()
                    bubble.setLineWidth_(1.2)
                    bubble.stroke()
            baseline = y + (pill_height - size) / 2 - 2
            foreground = color_from_hex(self.settings["text_color"], opacity)
            cursor = x + (13 if style != "纯文字" else 0)
            if icon is not None:
                icon.drawInRect_fromRect_operation_fraction_(
                    NSMakeRect(cursor, y + (pill_height - 16) / 2, 16, 16),
                    NSZeroRect, NSCompositingOperationSourceOver, opacity)
                cursor += 24
            family = self.settings["font_family"]
            source_face = barrage_font(size - 3, "source", family)
            project_face = barrage_font(size - 4, "project", family)
            message_face = barrage_font(size, "message", family)
            draw_barrage_text(source, (cursor, baseline + 1), source_face,
                              tint(kind, opacity), self.settings, opacity)
            cursor += measure(source, source_face) + 10
            if project:
                draw_barrage_text(project, (cursor, baseline + 1), project_face,
                                  color_from_hex(self.settings["text_color"], opacity * 0.66),
                                  self.settings, opacity * 0.66)
                cursor += measure(project, project_face) + 10
            draw_barrage_text(message, (cursor, baseline - 2), message_face,
                              foreground, self.settings, opacity)


class Controller(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        self.canvases, self.windows = [], []
        self.auto, self.paused, self.privacy, self.index = False, False, False, 0
        if self.demo_mode:
            from .sample_events import EVENTS
            self.sample_events = EVENTS
        self.live_count = 0
        self.progress_gate = ProgressGate()
        self.traffic_gate = TrafficGate()
        self.history = HistoryStore()
        self.settings = load_settings()
        self.sources = SourceRegistry()
        self.icons = IconResolver()
        self.screen_signature = None
        self.settings_window = None
        self.history_window = None
        self.integration_window = None
        self.custom_window = None
        self.notification_window = None
        self.wechat_watcher = WeChatNotificationWatcher()
        self.wechat_watcher.configure(self.settings["wechat_preview"], self.settings["wechat_ignored_chats"])
        if self.settings["wechat_enabled"]:
            self.wechat_watcher.start()
        ensure_spool()
        self.build_overlays()
        self.build_controls()
        self.build_status_item()
        self.tick_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1/60, self, "tick:", None, True)
        if self.demo_mode:
            self.event_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(2.4, self, "sample:", None, True)
        self.receive_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.1, self, "receive:", None, True)
        self.display_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(2, self, "checkDisplays:", None, True)
        NSApp().activateIgnoringOtherApps_(True)

    @objc.python_method
    def build_overlays(self):
        screens = list(NSScreen.screens())
        self.screen_signature = tuple((tuple(screen.frame()), screen.deviceDescription().get("NSScreenNumber"))
                                      for screen in screens)
        if self.settings["screens"] == "主屏幕":
            screens = screens[:1]
        reduce_motion = system_reduce_motion()
        for screen in screens:
            window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_screen_(screen.frame(), 0, NSBackingStoreBuffered, False, screen)
            window.setOpaque_(False)
            window.setBackgroundColor_(NSColor.clearColor())
            window.setHasShadow_(False)
            window.setLevel_(NSStatusWindowLevel)
            window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
            window.setIgnoresMouseEvents_(True)
            window.setReleasedWhenClosed_(False)
            canvas = Canvas.alloc().initWithFrame_(NSMakeRect(0, 0, screen.frame().size.width, screen.frame().size.height))
            canvas.settings = self.settings.copy()
            canvas.reduce_motion = self.settings["reduce_motion"] or reduce_motion
            canvas.paused = self.paused
            canvas.privacy = self.privacy
            window.setContentView_(canvas)
            window.orderFrontRegardless()
            self.canvases.append(canvas)
            self.windows.append(window)

    @objc.python_method
    def rebuild_overlays(self):
        for window in self.windows:
            window.orderOut_(None)
            window.close()
        self.windows, self.canvases = [], []
        self.build_overlays()

    @objc.typedSelector(b"v@:@")
    def checkDisplays_(self, timer):
        signature = tuple((tuple(screen.frame()), screen.deviceDescription().get("NSScreenNumber"))
                          for screen in NSScreen.screens())
        if signature != self.screen_signature:
            self.rebuild_overlays()
        else:
            reduce_motion = self.settings["reduce_motion"] or system_reduce_motion()
            for canvas in self.canvases:
                canvas.reduce_motion = reduce_motion
        if self.notification_window is not None and self.notification_window.isVisible():
            self.refresh_notification_status()

    @objc.python_method
    def label(self, content, value, size, y, bold=False, x=20, width=310):
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, 25))
        field.setStringValue_(value)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setTextColor_(NSColor.whiteColor() if bold else NSColor.lightGrayColor())
        field.setFont_(typeface(size, NSFontWeightBold if bold else NSFontWeightSemibold))
        content.addSubview_(field)
        return field

    @objc.python_method
    def button(self, content, title, y, action, x=20, width=310):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, 30))
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        content.addSubview_(button)
        return button

    @objc.python_method
    def build_controls(self):
        screen = NSScreen.mainScreen().visibleFrame()
        height = 350 if self.demo_mode else 245
        frame = NSMakeRect(screen.origin.x + screen.size.width - 378,
                           screen.origin.y + screen.size.height - height - 30, 350, height)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        self.control = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(frame, style, NSBackingStoreBuffered, False)
        self.control.setTitle_("AgentMarquee · 演示" if self.demo_mode else "AgentMarquee")
        self.control.setLevel_(NSStatusWindowLevel + 1)
        self.control.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.control.setReleasedWhenClosed_(False)
        self.control.setDelegate_(self)
        self.control.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.15, 1))
        content = self.control.contentView()
        if self.demo_mode:
            self.label(content, "AGENT MARQUEE", 19, 300, True)
            self.label(content, "演示模式 · 下方按钮使用模拟数据", 11, 275)
            self.status = self.label(content, "● 等待智能体事件", 12, 246)
            self.label(content, "模拟事件", 11, 215, True)
            self.button(content, "● 工作", 181, "sendWorking:", 20, 150)
            self.button(content, "! 需批准", 181, "sendAttention:", 180, 150)
            self.button(content, "✓ 完成", 145, "sendSuccess:", 20, 150)
            self.button(content, "× 错误", 145, "sendError:", 180, 150)
            self.auto_button = self.button(content, "开演示", 100, "toggleAuto:", 20, 98)
            self.pause_button = self.button(content, "暂停", 100, "togglePause:", 126, 98)
            self.privacy_button = self.button(content, "隐私模式", 100, "togglePrivacy:", 232, 98)
        else:
            self.label(content, "AGENT MARQUEE", 19, 195, True)
            self.label(content, "监听本机智能体事件与应用通知", 11, 170)
            self.status = self.label(content, "● 等待智能体事件", 12, 140)
            self.pause_button = self.button(content, "暂停", 98, "togglePause:", 20, 150)
            self.privacy_button = self.button(content, "隐私模式", 98, "togglePrivacy:", 180, 150)
        self.status.setTextColor_(NSColor.systemBlueColor())
        self.button(content, "智能体接入", 55, "openIntegrations:", 20, 310)
        self.button(content, "历史记录", 13, "openHistory:", 20, 150)
        self.button(content, "弹幕设置  ⚙", 13, "openSettings:", 180, 150)
        self.control.makeKeyAndOrderFront_(None)

    @objc.python_method
    def build_status_item(self):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setImage_(status_icon())
        self.status_item.button().setToolTip_("AgentMarquee · 弹幕通知")
        menu = NSMenu.alloc().initWithTitle_("AgentMarquee")
        for title, action in (("显示控制窗", "openControl:"),
                              ("弹幕设置", "openSettings:"),
                              ("历史记录", "openHistory:"),
                              ("智能体接入", "openIntegrations:"),
                              ("微信通知", "openNotifications:")):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(self)
            menu.addItem_(item)
        menu.addItem_(NSMenuItem.separatorItem())
        self.menu_pause_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("暂停弹幕", "togglePause:", "")
        self.menu_pause_item.setTarget_(self)
        menu.addItem_(self.menu_pause_item)
        self.menu_privacy_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("开启隐私模式", "togglePrivacy:", "")
        self.menu_privacy_item.setTarget_(self)
        menu.addItem_(self.menu_privacy_item)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("退出 AgentMarquee", "quitApp:", "")
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self.status_item.setMenu_(menu)

    @objc.python_method
    def build_history(self):
        main = self.control.frame()
        frame = NSMakeRect(main.origin.x - 460, main.origin.y + main.size.height - 430, 440, 430)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        self.history_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False)
        self.history_window.setTitle_("弹幕历史")
        self.history_window.setLevel_(NSStatusWindowLevel + 1)
        self.history_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.history_window.setReleasedWhenClosed_(False)
        self.history_window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.15, 1))
        content = self.history_window.contentView()
        self.history_count = self.label(content, "最近事件", 13, 387, True)
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 105, 400, 270))
        scroll.setHasVerticalScroller_(True)
        self.history_text = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 270))
        self.history_text.setEditable_(False)
        self.history_text.setSelectable_(True)
        self.history_text.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12, NSFontWeightSemibold))
        self.history_text.setTextColor_(NSColor.whiteColor())
        self.history_text.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.15, 1))
        scroll.setDocumentView_(self.history_text)
        content.addSubview_(scroll)
        self.history_link_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(20, 62, 292, 28), False)
        content.addSubview_(self.history_link_popup)
        self.history_open_button = self.button(content, "打开来源", 62, "openHistorySource:", 320, 100)
        self.button(content, "清空历史", 13, "clearHistory:", 20, 400)
        self.refresh_history()
        self.history_window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def build_integrations(self):
        main = self.control.frame()
        frame = NSMakeRect(main.origin.x - 480, main.origin.y + main.size.height - 430, 460, 430)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        self.integration_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False)
        self.integration_window.setTitle_("智能体接入")
        self.integration_window.setLevel_(NSStatusWindowLevel + 1)
        self.integration_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.integration_window.setReleasedWhenClosed_(False)
        self.integration_window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.15, 1))
        content = self.integration_window.contentView()
        self.label(content, "智能体接入", 18, 385, True, width=420)
        self.label(content, "按工具管理 Hook 配置；安装后可能需重启会话", 11, 360, width=420)
        self.integration_status_fields = {}
        for index, (agent, title) in enumerate(INTEGRATIONS):
            y = 303 - index * 85
            self.label(content, title, 14, y, True, width=420)
            self.integration_status_fields[agent] = self.label(content, "检查中", 11, y - 23, width=420)
            install = self.button(content, "安装 / 更新", y - 57, "installIntegration:", 20, 195)
            install.setTag_(index)
            remove = self.button(content, "卸载", y - 57, "removeIntegration:", 225, 195)
            remove.setTag_(index)
        self.button(content, "添加或管理其他来源", 30, "openCustomSources:", 20, 205)
        self.button(content, "微信通知", 30, "openNotifications:", 235, 205)
        self.label(content, "安装后请按各工具要求完成 Hook 信任审查", 10, 3, width=420)
        self.refresh_integrations()
        self.integration_window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def refresh_integrations(self):
        if self.integration_window is None:
            return
        for agent, _ in INTEGRATIONS:
            field = self.integration_status_fields[agent]
            try:
                count, total = integration_status(agent)
                path = str(CONFIG_PATHS[agent]).replace(str(Path.home()), "~", 1)
                field.setStringValue_(f"Hook 配置 {count}/{total} · {path}")
                field.setTextColor_(NSColor.lightGrayColor())
            except (OSError, ValueError, TypeError) as error:
                field.setStringValue_(f"配置读取失败：{error}")
                field.setTextColor_(NSColor.systemRedColor())

    @objc.python_method
    def build_custom_sources(self):
        main = self.control.frame()
        frame = NSMakeRect(main.origin.x - 480, main.origin.y + main.size.height - 460, 460, 460)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        self.custom_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False)
        self.custom_window.setTitle_("自定义来源")
        self.custom_window.setLevel_(NSStatusWindowLevel + 1)
        self.custom_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.custom_window.setReleasedWhenClosed_(False)
        self.custom_window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.15, 1))
        content = self.custom_window.contentView()
        self.label(content, "添加任意 AI 工具或对话来源", 17, 415, True, width=420)
        self.label(content, "建立来源后，将下方命令放入该工具的 Hook 或自动化中", 11, 391, width=420)
        self.label(content, "显示名称", 12, 350, True, width=100)
        self.custom_name = NSTextField.alloc().initWithFrame_(NSMakeRect(130, 346, 300, 25))
        self.custom_name.setPlaceholderString_("例如：我的 AI 对话")
        content.addSubview_(self.custom_name)
        self.label(content, "来源标识", 12, 310, True, width=100)
        self.custom_id = NSTextField.alloc().initWithFrame_(NSMakeRect(130, 306, 300, 25))
        self.custom_id.setPlaceholderString_("例如：my-chat，英文小写")
        content.addSubview_(self.custom_id)
        self.button(content, "添加来源", 265, "addCustomSource:", 20, 420)
        self.custom_status = self.label(content, "无需修改程序代码；最多添加 50 个来源", 11, 232, width=420)
        self.label(content, "已有来源", 12, 199, True, width=420)
        self.custom_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(20, 162, 300, 28), False)
        self.custom_popup.setTarget_(self)
        self.custom_popup.setAction_("customSelectionChanged:")
        content.addSubview_(self.custom_popup)
        self.custom_test = self.button(content, "测试", 162, "testCustomSource:", 330, 100)
        self.custom_icon_choose = self.button(content, "选择图标", 126, "chooseCustomIcon:", 20, 110)
        self.custom_icon_clear = self.button(content, "清除图标", 126, "clearCustomIcon:", 135, 85)
        self.custom_toggle = self.button(content, "暂停来源", 126, "toggleCustomSource:", 230, 90)
        self.custom_remove = self.button(content, "删除", 126, "removeCustomSource:", 330, 100)
        self.label(content, "接入命令", 11, 94, width=200)
        self.custom_copy = self.button(content, "复制命令", 91, "copyCustomCommand:", 330, 100)
        command_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 16, 410, 73))
        command_scroll.setHasVerticalScroller_(True)
        self.custom_command = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 410, 73))
        self.custom_command.setEditable_(False)
        self.custom_command.setSelectable_(True)
        self.custom_command.setFont_(NSFont.monospacedSystemFontOfSize_weight_(10, NSFontWeightRegular))
        self.custom_command.setTextColor_(NSColor.whiteColor())
        self.custom_command.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.05, 0.07, 0.11, 1))
        command_scroll.setDocumentView_(self.custom_command)
        content.addSubview_(command_scroll)
        self.refresh_custom_sources()
        self.custom_window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def refresh_custom_sources(self, selected=None):
        try:
            items = load_sources()
        except (OSError, ValueError, TypeError) as error:
            self.custom_status.setStringValue_(f"读取失败：{error}")
            items = []
        self.custom_ids = [item["id"] for item in items]
        self.custom_enabled = {item["id"]: item["enabled"] for item in items}
        self.custom_icons = {item["id"]: item["icon"] for item in items}
        self.custom_popup.removeAllItems()
        if items:
            self.custom_popup.addItemsWithTitles_([f"{item['name']} · {item['id']}" for item in items])
            if selected in self.custom_ids:
                self.custom_popup.selectItemAtIndex_(self.custom_ids.index(selected))
            self.custom_test.setEnabled_(self.custom_enabled.get(self.selected_custom_id(), True))
            self.custom_toggle.setEnabled_(True)
            self.custom_remove.setEnabled_(True)
            self.custom_copy.setEnabled_(True)
            self.custom_icon_choose.setEnabled_(True)
        else:
            self.custom_popup.addItemWithTitle_("暂无来源")
            self.custom_test.setEnabled_(False)
            self.custom_toggle.setEnabled_(False)
            self.custom_remove.setEnabled_(False)
            self.custom_copy.setEnabled_(False)
            self.custom_icon_choose.setEnabled_(False)
        self.update_custom_command()
        self.update_custom_toggle()
        self.custom_icon_clear.setEnabled_(bool(self.custom_icons.get(self.selected_custom_id())))
        self.sources.refresh(force=True)

    @objc.python_method
    def selected_custom_id(self):
        index = self.custom_popup.indexOfSelectedItem()
        return self.custom_ids[index] if 0 <= index < len(self.custom_ids) else None

    @objc.python_method
    def update_custom_command(self):
        source_id = self.selected_custom_id()
        if source_id is None:
            self.custom_command.setString_("添加来源后，这里会给出可复制的接入命令。")
            return
        checkout_script = Path(__file__).resolve().parents[2] / "bin" / "agent-marquee-send"
        if getattr(sys, "frozen", False):
            prefix = f"{shlex.quote(sys.executable)} --send"
        elif checkout_script.is_file():
            prefix = f"/usr/bin/env python3 {shlex.quote(str(checkout_script))}"
        else:
            prefix = shlex.quote(str(Path(sys.executable).parent / "agent-marquee-send"))
        self.custom_command.setString_(
            f'{prefix} --agent {source_id} --kind success --message "回答已完成" --project "对话"')

    @objc.python_method
    def update_custom_toggle(self):
        source_id = self.selected_custom_id()
        self.custom_toggle.setTitle_("暂停来源" if self.custom_enabled.get(source_id, True) else "启用来源")

    @objc.python_method
    def change_integration(self, sender, uninstall):
        agent = INTEGRATIONS[sender.tag()][0]
        try:
            apply_agent(agent, uninstall=uninstall)
            self.refresh_integrations()
        except (OSError, ValueError, TypeError) as error:
            field = self.integration_status_fields[agent]
            field.setStringValue_(f"操作失败：{error}")
            field.setTextColor_(NSColor.systemRedColor())

    @objc.python_method
    def refresh_history(self):
        if self.history_window is None:
            return
        self.history_count.setStringValue_(f"最近事件 · {len(self.history)} 条（仅内存）")
        rows = []
        linked = []
        for item in self.history.recent():
            clock = datetime.fromtimestamp(item["occurred_at"]).strftime("%H:%M:%S")
            marker = " ↗" if item["open_url"] else ""
            rows.append(f"{clock}  [{item['origin']}] {item['source']}{marker}\n    {item['message']}")
            if item["open_url"]:
                linked.append((f"{clock} · {item['source']} · {item['message'][:20]}", item["open_url"]))
        self.history_text.setString_("\n\n".join(rows) if rows else "暂无弹幕记录")
        selected_url = self.selected_history_url() if hasattr(self, "history_urls") else None
        self.history_urls = [url for _, url in linked]
        self.history_link_popup.removeAllItems()
        if linked:
            self.history_link_popup.addItemsWithTitles_([label for label, _ in linked])
            if selected_url in self.history_urls:
                self.history_link_popup.selectItemAtIndex_(self.history_urls.index(selected_url))
        else:
            self.history_link_popup.addItemWithTitle_("暂无可打开的来源")
        self.history_open_button.setEnabled_(bool(linked))

    @objc.python_method
    def selected_history_url(self):
        index = self.history_link_popup.indexOfSelectedItem()
        return self.history_urls[index] if 0 <= index < len(self.history_urls) else None

    @objc.python_method
    def build_settings(self):
        NSColorPanel.sharedColorPanel().setLevel_(NSStatusWindowLevel + 2)
        main = self.control.frame()
        frame = NSMakeRect(main.origin.x - 410, main.origin.y + main.size.height - 720, 390, 720)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        self.settings_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False)
        self.settings_window.setTitle_("弹幕样式与配置")
        self.settings_window.setLevel_(NSStatusWindowLevel + 1)
        self.settings_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.settings_window.setReleasedWhenClosed_(False)
        self.settings_window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.15, 1))
        content = self.settings_window.contentView()
        self.label(content, "弹幕设置", 18, 674, True)
        self.label(content, "调整后即时预览，并自动保存", 11, 651)
        self.label(content, "样式", 12, 610, True)
        self.style_popup = self.popup(content, ["胶囊", "轻盈", "纯文字"], self.settings["style"], 604, width=110)
        self.label(content, "字体", 12, 610, True, x=236, width=38)
        self.font_popup = self.popup(content, ["苹方", "系统", "冬青", "宋体", "华文黑体"],
                                     self.settings["font_family"], 604, x=276, width=94)
        self.label(content, "文字颜色", 12, 575, True)
        self.text_color_well = NSColorWell.alloc().initWithFrame_(NSMakeRect(119, 569, 251, 28))
        self.text_color_well.setColor_(color_from_hex(self.settings["text_color"]))
        self.text_color_well.setTarget_(self)
        self.text_color_well.setAction_("settingsChanged:")
        content.addSubview_(self.text_color_well)
        self.label(content, "文字描边", 12, 537, True)
        self.outline_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(119, 532, 24, 24))
        self.outline_checkbox.setButtonType_(NSSwitchButton)
        self.outline_checkbox.setTitle_("")
        self.outline_checkbox.setAccessibilityLabel_("启用文字描边")
        self.outline_checkbox.setState_(NSControlStateValueOn if self.settings["outline_enabled"] else NSControlStateValueOff)
        self.outline_checkbox.setTarget_(self)
        self.outline_checkbox.setAction_("settingsChanged:")
        content.addSubview_(self.outline_checkbox)
        self.label(content, "启用", 11, 532, x=143, width=38)
        self.outline_color_well = NSColorWell.alloc().initWithFrame_(NSMakeRect(184, 531, 90, 28))
        self.outline_color_well.setColor_(color_from_hex(self.settings["outline_color"]))
        self.outline_color_well.setAccessibilityLabel_("描边颜色")
        self.outline_color_well.setTarget_(self)
        self.outline_color_well.setAction_("settingsChanged:")
        content.addSubview_(self.outline_color_well)
        self.outline_width_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(281, 531, 89, 28), False)
        self.outline_width_popup.addItemsWithTitles_(["0.5 px", "1 px", "1.5 px"])
        self.outline_width_popup.selectItemAtIndex_(min(range(3), key=lambda index:
            abs((0.5, 1.0, 1.5)[index] - self.settings["outline_width"])))
        self.outline_width_popup.setAccessibilityLabel_("描边粗细")
        self.outline_width_popup.setTarget_(self)
        self.outline_width_popup.setAction_("settingsChanged:")
        content.addSubview_(self.outline_width_popup)
        self.refresh_outline_controls()
        self.label(content, "区域", 12, 501, True)
        self.region_popup = self.popup(content, ["顶部", "中部", "底部"], self.settings["region"], 495)
        self.label(content, "显示器", 12, 465, True)
        self.screen_popup = self.popup(content, ["所有屏幕", "主屏幕"], self.settings["screens"], 459)
        self.label(content, "播放方式", 12, 429, True)
        self.motion_popup = self.popup(content, ["滚动", "固定停留"], self.settings["motion"], 423)
        self.slider_values = {}
        self.font_slider = self.slider_row(content, "字号", 393, 12, 22, self.settings["font_size"])
        self.speed_slider = self.slider_row(content, "滚动速度", 358, 0.5, 2.0, self.settings["speed"])
        self.opacity_slider = self.slider_row(content, "透明度", 323, 0.4, 1.0, self.settings["opacity"])
        self.spacing_slider = self.slider_row(content, "行间距", 288, 42, 80, self.settings["spacing"])
        self.coverage_slider = self.slider_row(content, "区域占比", 253, 0.2, 0.8, self.settings["coverage"])
        self.density_slider = self.slider_row(content, "同屏密度", 218, 1, 12, self.settings["density"])
        self.duration_slider = self.slider_row(content, "固定时长", 183, 2, 10, self.settings["fixed_duration"])
        self.icons_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(119, 150, 24, 24))
        self.icons_checkbox.setButtonType_(NSSwitchButton)
        self.icons_checkbox.setTitle_("")
        self.icons_checkbox.setAccessibilityLabel_("显示来源图标")
        self.icons_checkbox.setState_(NSControlStateValueOn if self.settings["show_icons"] else NSControlStateValueOff)
        self.icons_checkbox.setTarget_(self)
        self.icons_checkbox.setAction_("settingsChanged:")
        content.addSubview_(self.icons_checkbox)
        self.label(content, "图标（非纯文字）", 11, 149, x=150, width=115)
        self.motion_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(265, 150, 24, 24))
        self.motion_checkbox.setButtonType_(NSSwitchButton)
        self.motion_checkbox.setTitle_("")
        self.motion_checkbox.setAccessibilityLabel_("减少动态效果")
        self.motion_checkbox.setState_(NSControlStateValueOn if self.settings["reduce_motion"] else NSControlStateValueOff)
        self.motion_checkbox.setTarget_(self)
        self.motion_checkbox.setAction_("settingsChanged:")
        content.addSubview_(self.motion_checkbox)
        self.label(content, "减少动画", 11, 149, x=290, width=90)
        self.label(content, "类型过滤", 12, 115, True)
        self.filter_popup = self.popup(content, ["全部类型", "隐藏工作", "只看需处理"], self.settings["event_filter"], 109)
        self.label(content, "内容", 12, 77, True)
        self.content_popup = self.popup(content, ["简洁摘要", "部分详情"], self.settings["content"], 71)
        self.label(content, "进度弹幕", 12, 40, True)
        self.progress_popup = self.popup(content, ["精简", "全部"], self.settings["progress"], 34)
        self.refresh_slider_values()
        self.settings_window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def build_notifications(self):
        main = self.control.frame()
        frame = NSMakeRect(main.origin.x - 460, main.origin.y + main.size.height - 340, 440, 340)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        self.notification_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False)
        self.notification_window.setTitle_("微信通知")
        self.notification_window.setLevel_(NSStatusWindowLevel + 1)
        self.notification_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.notification_window.setReleasedWhenClosed_(False)
        self.notification_window.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.15, 1))
        content = self.notification_window.contentView()
        self.label(content, "个人微信 Mac 客户端", 17, 295, True, width=400)
        self.label(content, "读取 macOS 已显示的通知；此功能默认关闭", 11, 270, width=400)
        self.wechat_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(20, 225, 390, 26))
        self.wechat_checkbox.setButtonType_(NSSwitchButton)
        self.wechat_checkbox.setTitle_("将微信新消息显示为弹幕")
        self.wechat_checkbox.setState_(NSControlStateValueOn if self.settings["wechat_enabled"] else NSControlStateValueOff)
        self.wechat_checkbox.setTarget_(self)
        self.wechat_checkbox.setAction_("notificationSettingsChanged:")
        content.addSubview_(self.wechat_checkbox)
        self.wechat_preview_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(20, 191, 390, 26))
        self.wechat_preview_checkbox.setButtonType_(NSSwitchButton)
        self.wechat_preview_checkbox.setTitle_("显示发送人和通知预览（可能包含私人内容）")
        self.wechat_preview_checkbox.setState_(NSControlStateValueOn if self.settings["wechat_preview"] else NSControlStateValueOff)
        self.wechat_preview_checkbox.setTarget_(self)
        self.wechat_preview_checkbox.setAction_("notificationSettingsChanged:")
        content.addSubview_(self.wechat_preview_checkbox)
        self.label(content, "忽略会话名称（逗号分隔）", 11, 150, width=400)
        self.wechat_ignored_field = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 119, 400, 27))
        self.wechat_ignored_field.setPlaceholderString_("例如：工作群, 家庭群")
        self.wechat_ignored_field.setStringValue_(", ".join(self.settings["wechat_ignored_chats"]))
        self.wechat_ignored_field.setTarget_(self)
        self.wechat_ignored_field.setAction_("notificationSettingsChanged:")
        self.wechat_ignored_field.setDelegate_(self)
        content.addSubview_(self.wechat_ignored_field)
        self.wechat_permission_status = self.label(content, "检查中", 11, 79, width=400)
        self.button(content, "请求辅助功能权限", 31, "requestAccessibility:", 20, 195)
        self.button(content, "测试微信弹幕", 31, "testWeChatNotification:", 225, 195)
        self.wechat_preview_checkbox.setEnabled_(self.settings["wechat_enabled"])
        self.refresh_notification_status()
        self.notification_window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def refresh_notification_status(self):
        if not self.settings["wechat_enabled"]:
            value = "状态：已关闭；不读取通知"
        elif accessibility_trusted():
            value = "状态：已授权；等待微信新通知（仅处理可见通知）"
        else:
            value = "状态：需要在系统设置中授予辅助功能权限"
        self.wechat_permission_status.setStringValue_(value)

    @objc.python_method
    def popup(self, content, values, selected, y, x=119, width=251):
        control = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(x, y, width, 28), False)
        control.addItemsWithTitles_(values)
        control.selectItemWithTitle_(selected)
        control.setTarget_(self)
        control.setAction_("settingsChanged:")
        content.addSubview_(control)
        return control

    @objc.python_method
    def slider_row(self, content, title, y, minimum, maximum, value):
        self.label(content, title, 12, y + 1, True)
        slider = NSSlider.alloc().initWithFrame_(NSMakeRect(119, y, 185, 24))
        slider.setMinValue_(minimum)
        slider.setMaxValue_(maximum)
        slider.setDoubleValue_(value)
        slider.setTarget_(self)
        slider.setAction_("settingsChanged:")
        content.addSubview_(slider)
        self.slider_values[title] = self.label(content, "", 11, y, x=315, width=55)
        return slider

    @objc.python_method
    def refresh_slider_values(self):
        values = {
            "字号": f'{round(self.font_slider.doubleValue())} px',
            "滚动速度": f'{self.speed_slider.doubleValue():.1f}×',
            "透明度": f'{round(self.opacity_slider.doubleValue() * 100)}%',
            "行间距": f'{round(self.spacing_slider.doubleValue())} px',
            "区域占比": f'{round(self.coverage_slider.doubleValue() * 100)}%',
            "同屏密度": f'{round(self.density_slider.doubleValue())} 条',
            "固定时长": f'{round(self.duration_slider.doubleValue())} 秒',
        }
        for title, value in values.items():
            self.slider_values[title].setStringValue_(value)

    @objc.python_method
    def refresh_outline_controls(self):
        enabled = self.outline_checkbox.state() == NSControlStateValueOn
        self.outline_color_well.setEnabled_(enabled)
        self.outline_width_popup.setEnabled_(enabled)

    @objc.python_method
    def emit(self, source, message, kind, origin="模拟", detail="", agent_id=None, open_url=""):
        shown = f"{message} · {detail}" if detail and self.settings["content"] == "部分详情" else message
        self.history.add(source, shown, kind, origin, private=self.privacy, open_url=open_url)
        self.refresh_history()
        icon = self.icons.resolve(agent_id, self.sources.icon_path(agent_id)) if agent_id else None
        for canvas in self.canvases:
            canvas.emit(source, shown, kind, icon)

    @objc.python_method
    def refresh(self):
        if self.paused:
            text, hue = "Ⅱ 弹幕已暂停", NSColor.systemOrangeColor()
        elif self.auto:
            text, hue = ("● 演示中 · 隐私模式" if self.privacy else "● 模拟演示运行中"), NSColor.systemGreenColor()
        else:
            text = f"● 已收到 {self.live_count} 条事件" if self.live_count else "● 等待新事件"
            hue = NSColor.systemBlueColor()
        self.status.setStringValue_(text)
        self.status.setTextColor_(hue)
        if hasattr(self, "menu_pause_item"):
            pause_title = "继续弹幕" if self.paused else "暂停弹幕"
            privacy_title = "关闭隐私模式" if self.privacy else "开启隐私模式"
            if self.menu_pause_item.title() != pause_title:
                self.menu_pause_item.setTitle_(pause_title)
            if self.menu_privacy_item.title() != privacy_title:
                self.menu_privacy_item.setTitle_(privacy_title)

    @objc.typedSelector(b"v@:@")
    def tick_(self, timer):
        for canvas in self.canvases:
            canvas.tick()

    @objc.typedSelector(b"v@:@")
    def sample_(self, timer):
        if self.auto and not self.paused:
            self.emit(*self.sample_events[self.index % len(self.sample_events)])
            self.index += 1

    @objc.typedSelector(b"v@:@")
    def receive_(self, timer):
        events = prioritize(drain(50))
        if events:
            self.sources.refresh()
        for event in events:
            if not self.sources.is_enabled(event["agent"]):
                continue
            self.live_count += 1
            if (not self.paused and self.traffic_gate.show(event)
                    and self.progress_gate.show(event, self.settings["progress"], self.settings["event_filter"])):
                agent = {"codex": "CODEX", "claude-code": "CLAUDE CODE", "codebuddy": "CODEBUDDY", "wechat": "微信"}.get(
                    event["agent"]) or self.sources.display_name(event["agent"]) or event["agent"].upper()
                source = f"{agent} · {event['project']}" if event["project"] else agent
                self.emit(source, event["message"], event["kind"], origin="真实",
                          detail=event.get("detail", ""), agent_id=event["agent"],
                          open_url=event.get("open_url", ""))
        self.refresh()

    @objc.typedSelector(b"v@:@")
    def sendWorking_(self, sender): self.emit("CODEX · AgentMarquee", "正在生成界面并检查效果", "working", detail="macos.py")
    @objc.typedSelector(b"v@:@")
    def sendAttention_(self, sender): self.emit("CODEX · AgentMarquee", "需要批准：运行终端命令", "attention")
    @objc.typedSelector(b"v@:@")
    def sendSuccess_(self, sender): self.emit("CODEX · AgentMarquee", "任务已完成，可以查看结果", "success")
    @objc.typedSelector(b"v@:@")
    def sendError_(self, sender): self.emit("CODEX · AgentMarquee", "执行失败，请查看任务详情", "error")

    @objc.typedSelector(b"v@:@")
    def toggleAuto_(self, sender):
        self.auto = not self.auto
        self.auto_button.setTitle_("停演示" if self.auto else "开演示")
        self.refresh()

    @objc.typedSelector(b"v@:@")
    def togglePause_(self, sender):
        self.paused = not self.paused
        for canvas in self.canvases: canvas.paused = self.paused
        self.pause_button.setTitle_("继续" if self.paused else "暂停")
        self.refresh()

    @objc.typedSelector(b"v@:@")
    def togglePrivacy_(self, sender):
        self.privacy = not self.privacy
        self.wechat_watcher.configure(self.settings["wechat_preview"] and not self.privacy,
                                      self.settings["wechat_ignored_chats"])
        if self.privacy:
            self.history.clear()
            self.refresh_history()
        for canvas in self.canvases:
            canvas.privacy = self.privacy
            canvas.items.clear()
            canvas.setNeedsDisplay_(True)
        self.privacy_button.setTitle_("隐私: 开" if self.privacy else "隐私模式")
        self.refresh()
        self.emit("AGENT MARQUEE", "隐私模式已切换", "success", origin="系统")

    @objc.typedSelector(b"v@:@")
    def openHistory_(self, sender):
        if self.history_window is None:
            self.build_history()
        else:
            self.refresh_history()
            self.history_window.makeKeyAndOrderFront_(None)

    @objc.typedSelector(b"v@:@")
    def openControl_(self, sender):
        self.control.makeKeyAndOrderFront_(None)
        NSApp().activateIgnoringOtherApps_(True)

    @objc.typedSelector(b"v@:@")
    def quitApp_(self, sender):
        self.wechat_watcher.stop()
        NSApp().terminate_(None)

    @objc.typedSelector(b"v@:@")
    def clearHistory_(self, sender):
        self.history.clear()
        self.refresh_history()

    @objc.typedSelector(b"v@:@")
    def openHistorySource_(self, sender):
        url = self.selected_history_url()
        if url:
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    @objc.typedSelector(b"v@:@")
    def openIntegrations_(self, sender):
        if self.integration_window is None:
            self.build_integrations()
        else:
            self.refresh_integrations()
            self.integration_window.makeKeyAndOrderFront_(None)

    @objc.typedSelector(b"v@:@")
    def installIntegration_(self, sender):
        self.change_integration(sender, uninstall=False)

    @objc.typedSelector(b"v@:@")
    def removeIntegration_(self, sender):
        self.change_integration(sender, uninstall=True)

    @objc.typedSelector(b"v@:@")
    def openCustomSources_(self, sender):
        if self.custom_window is None:
            self.build_custom_sources()
        else:
            self.refresh_custom_sources(self.selected_custom_id())
            self.custom_window.makeKeyAndOrderFront_(None)

    @objc.typedSelector(b"v@:@")
    def addCustomSource_(self, sender):
        source_id = self.custom_id.stringValue().strip()
        name = self.custom_name.stringValue()
        try:
            add_source(source_id, name)
            self.custom_status.setStringValue_(f"已添加：{name}")
            self.custom_status.setTextColor_(NSColor.systemGreenColor())
            self.custom_name.setStringValue_("")
            self.custom_id.setStringValue_("")
            self.refresh_custom_sources(source_id)
        except (OSError, ValueError, TypeError) as error:
            self.custom_status.setStringValue_(f"添加失败：{error}")
            self.custom_status.setTextColor_(NSColor.systemRedColor())

    @objc.typedSelector(b"v@:@")
    def removeCustomSource_(self, sender):
        source_id = self.selected_custom_id()
        if source_id is None:
            return
        try:
            remove_source(source_id)
            self.custom_status.setStringValue_(f"已删除来源：{source_id}")
            self.custom_status.setTextColor_(NSColor.lightGrayColor())
            self.refresh_custom_sources()
        except (OSError, ValueError, TypeError) as error:
            self.custom_status.setStringValue_(f"删除失败：{error}")
            self.custom_status.setTextColor_(NSColor.systemRedColor())

    @objc.typedSelector(b"v@:@")
    def testCustomSource_(self, sender):
        source_id = self.selected_custom_id()
        if source_id is None:
            return
        event = make_event(source_id, "test", "success", "接入测试成功", "对话")
        if publish(event):
            self.custom_status.setStringValue_(f"测试弹幕已发送：{source_id}")
            self.custom_status.setTextColor_(NSColor.systemGreenColor())
        else:
            self.custom_status.setStringValue_("测试发送失败，请检查本机事件目录")
            self.custom_status.setTextColor_(NSColor.systemRedColor())

    @objc.typedSelector(b"v@:@")
    def customSelectionChanged_(self, sender):
        self.update_custom_command()
        self.update_custom_toggle()
        self.custom_test.setEnabled_(self.custom_enabled.get(self.selected_custom_id(), True))
        self.custom_icon_clear.setEnabled_(bool(self.custom_icons.get(self.selected_custom_id())))

    @objc.typedSelector(b"v@:@")
    def chooseCustomIcon_(self, sender):
        source_id = self.selected_custom_id()
        if source_id is None:
            return
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["png", "jpg", "jpeg", "icns"])
        if panel.runModal() != NSModalResponseOK:
            return
        try:
            set_source_icon(source_id, panel.URL().path())
            self.icons.invalidate(source_id)
            self.refresh_custom_sources(source_id)
            self.custom_status.setStringValue_(f"已设置 {source_id} 的图标")
            self.custom_status.setTextColor_(NSColor.systemGreenColor())
        except (OSError, ValueError, TypeError) as error:
            self.custom_status.setStringValue_(f"图标设置失败：{error}")
            self.custom_status.setTextColor_(NSColor.systemRedColor())

    @objc.typedSelector(b"v@:@")
    def clearCustomIcon_(self, sender):
        source_id = self.selected_custom_id()
        if source_id is None:
            return
        try:
            set_source_icon(source_id, None)
            self.icons.invalidate(source_id)
            self.refresh_custom_sources(source_id)
            self.custom_status.setStringValue_(f"已恢复 {source_id} 的默认图标")
            self.custom_status.setTextColor_(NSColor.lightGrayColor())
        except (OSError, ValueError, TypeError) as error:
            self.custom_status.setStringValue_(f"清除图标失败：{error}")
            self.custom_status.setTextColor_(NSColor.systemRedColor())

    @objc.typedSelector(b"v@:@")
    def toggleCustomSource_(self, sender):
        source_id = self.selected_custom_id()
        if source_id is None:
            return
        enabled = not self.custom_enabled[source_id]
        try:
            set_source_enabled(source_id, enabled)
            self.refresh_custom_sources(source_id)
            self.custom_status.setStringValue_(f"{source_id} 已{'启用' if enabled else '暂停'}")
            self.custom_status.setTextColor_(NSColor.systemGreenColor() if enabled else NSColor.systemOrangeColor())
        except (OSError, ValueError, TypeError) as error:
            self.custom_status.setStringValue_(f"操作失败：{error}")
            self.custom_status.setTextColor_(NSColor.systemRedColor())

    @objc.typedSelector(b"v@:@")
    def copyCustomCommand_(self, sender):
        source_id = self.selected_custom_id()
        if source_id is None:
            return
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        if board.setString_forType_(self.custom_command.string(), NSPasteboardTypeString):
            self.custom_status.setStringValue_(f"已复制 {source_id} 的接入命令")
            self.custom_status.setTextColor_(NSColor.systemGreenColor())
        else:
            self.custom_status.setStringValue_("复制失败，请手动选中命令")
            self.custom_status.setTextColor_(NSColor.systemRedColor())

    @objc.typedSelector(b"v@:@")
    def openSettings_(self, sender):
        if self.settings_window is None:
            self.build_settings()
        else:
            self.settings_window.makeKeyAndOrderFront_(None)

    @objc.typedSelector(b"v@:@")
    def openNotifications_(self, sender):
        if self.notification_window is None:
            self.build_notifications()
        else:
            self.refresh_notification_status()
            self.notification_window.makeKeyAndOrderFront_(None)

    @objc.typedSelector(b"v@:@")
    def notificationSettingsChanged_(self, sender):
        enabled = self.wechat_checkbox.state() == NSControlStateValueOn
        preview = self.wechat_preview_checkbox.state() == NSControlStateValueOn
        ignored = [name.strip() for name in self.wechat_ignored_field.stringValue().split(",") if name.strip()]
        self.settings.update({"wechat_enabled": enabled, "wechat_preview": preview,
                              "wechat_ignored_chats": ignored})
        save_settings(self.settings)
        self.settings = load_settings()
        self.wechat_watcher.configure(self.settings["wechat_preview"] and not self.privacy,
                                      self.settings["wechat_ignored_chats"])
        if enabled:
            self.wechat_watcher.start()
        else:
            self.wechat_watcher.stop()
        self.wechat_preview_checkbox.setEnabled_(enabled)
        self.refresh_notification_status()

    def controlTextDidEndEditing_(self, notification):
        if (self.notification_window is not None
                and notification.object() is self.wechat_ignored_field):
            self.notificationSettingsChanged_(self.wechat_ignored_field)

    @objc.typedSelector(b"v@:@")
    def requestAccessibility_(self, sender):
        accessibility_trusted(prompt=True)
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"))
        self.refresh_notification_status()

    @objc.typedSelector(b"v@:@")
    def testWeChatNotification_(self, sender):
        self.emit("微信", "有新消息", "attention", origin="预览", agent_id="wechat")

    @objc.typedSelector(b"v@:@")
    def settingsChanged_(self, sender):
        self.refresh_slider_values()
        self.refresh_outline_controls()
        self.settings = {
            "style": self.style_popup.titleOfSelectedItem(),
            "font_family": self.font_popup.titleOfSelectedItem(),
            "text_color": color_to_hex(self.text_color_well.color()),
            "outline_enabled": self.outline_checkbox.state() == NSControlStateValueOn,
            "outline_color": color_to_hex(self.outline_color_well.color()),
            "outline_width": (0.5, 1.0, 1.5)[self.outline_width_popup.indexOfSelectedItem()],
            "region": self.region_popup.titleOfSelectedItem(),
            "screens": self.screen_popup.titleOfSelectedItem(),
            "motion": self.motion_popup.titleOfSelectedItem(),
            "font_size": round(self.font_slider.doubleValue()),
            "speed": round(self.speed_slider.doubleValue(), 2),
            "opacity": round(self.opacity_slider.doubleValue(), 2),
            "spacing": round(self.spacing_slider.doubleValue()),
            "coverage": round(self.coverage_slider.doubleValue(), 2),
            "density": round(self.density_slider.doubleValue()),
            "fixed_duration": round(self.duration_slider.doubleValue()),
            "show_icons": self.icons_checkbox.state() == NSControlStateValueOn,
            "reduce_motion": self.motion_checkbox.state() == NSControlStateValueOn,
            "event_filter": self.filter_popup.titleOfSelectedItem(),
            "content": self.content_popup.titleOfSelectedItem(),
            "progress": self.progress_popup.titleOfSelectedItem(),
            "wechat_enabled": self.settings["wechat_enabled"],
            "wechat_preview": self.settings["wechat_preview"],
            "wechat_ignored_chats": self.settings["wechat_ignored_chats"],
        }
        save_settings(self.settings)
        self.rebuild_overlays()
        self.emit("CODEX · AgentMarquee", "弹幕样式预览", "success", origin="预览", agent_id="codex")

    def windowWillClose_(self, notification):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="AgentMarquee macOS desktop overlay")
    parser.add_argument("--demo", action="store_true", help="show simulated event controls")
    args = parser.parse_args(argv)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = Controller.alloc().init()
    controller.demo_mode = args.demo
    app.setDelegate_(controller)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
