"""Resolve local source artwork without bundling third-party trademarks."""

from pathlib import Path

from AppKit import (NSBezierPath, NSColor, NSFont, NSFontAttributeName,
                    NSForegroundColorAttributeName, NSImage, NSMakeRect,
                    NSMakeSize, NSWorkspace)
from Foundation import NSString


APP_BUNDLES = {
    "codex": ("com.openai.codex",),
    "claude-code": ("com.anthropic.claudefordesktop", "com.anthropic.claude"),
    "codebuddy": ("com.tencent.codebuddycn",),
    "wechat": ("com.tencent.xinWeChat", "com.tencent.WeChat"),
}
FALLBACK_COLORS = {
    "codex": (0.22, 0.25, 0.30),
    "claude-code": (0.79, 0.47, 0.34),
    "codebuddy": (0.24, 0.53, 0.94),
    "wechat": (0.13, 0.75, 0.42),
}


def fallback_icon(source_id):
    icon = NSImage.alloc().initWithSize_(NSMakeSize(20, 20))
    icon.lockFocus()
    red, green, blue = FALLBACK_COLORS.get(source_id, (0.38, 0.45, 0.60))
    NSColor.colorWithCalibratedRed_green_blue_alpha_(red, green, blue, 1).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(0, 0, 20, 20), 5, 5).fill()
    label = (source_id[:1] or "?").upper()
    face = NSFont.systemFontOfSize_weight_(12, 0.6)
    attrs = {NSFontAttributeName: face, NSForegroundColorAttributeName: NSColor.whiteColor()}
    width = NSString.stringWithString_(label).sizeWithAttributes_(attrs).width
    NSString.stringWithString_(label).drawAtPoint_withAttributes_(((20 - width) / 2, 2), attrs)
    icon.unlockFocus()
    return icon


class IconResolver:
    def __init__(self):
        self._cache = {}

    def resolve(self, source_id, custom_path=None):
        key = (source_id, str(custom_path) if custom_path else None)
        if key in self._cache:
            return self._cache[key]
        image = None
        if custom_path:
            path = Path(custom_path)
            if path.is_file() and not path.is_symlink():
                image = NSImage.alloc().initWithContentsOfFile_(str(path))
                if image is not None and not image.isValid():
                    image = None
        if image is None:
            workspace = NSWorkspace.sharedWorkspace()
            for bundle_id in APP_BUNDLES.get(source_id, ()):
                url = workspace.URLForApplicationWithBundleIdentifier_(bundle_id)
                if url:
                    if source_id == "codex":
                        resources = Path(url.path()) / "Contents" / "Resources"
                        for filename in ("icon-codex-dark-color.png", "icon-codex-light.png"):
                            artwork = resources / filename
                            if artwork.is_file():
                                candidate = NSImage.alloc().initWithContentsOfFile_(str(artwork))
                                if candidate is not None and candidate.isValid():
                                    image = candidate
                                    break
                    if image is not None:
                        break
                    image = workspace.iconForFile_(url.path())
                    break
        if image is None:
            image = fallback_icon(source_id)
        self._cache[key] = image
        return image

    def invalidate(self, source_id):
        self._cache = {key: value for key, value in self._cache.items() if key[0] != source_id}
