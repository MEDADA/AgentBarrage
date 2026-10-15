"""User settings stored outside the source checkout."""

import json
import os
import re
import tempfile
from pathlib import Path
from .migration import DATA_DIR, migrate_user_data

SETTINGS_PATH = DATA_DIR / "settings.json"
LEGACY_PATH = Path(__file__).resolve().parents[2] / "demo" / "settings.json"
DEFAULT_SETTINGS = {
    "style": "胶囊", "font_family": "苹方", "region": "顶部", "font_size": 16, "speed": 1.0,
    "opacity": 0.93, "spacing": 54, "content": "简洁摘要", "progress": "精简",
    "text_color": "#FFFFFF", "outline_enabled": False,
    "outline_color": "#141A26", "outline_width": 0.5,
    "motion": "滚动", "density": 6,
    "coverage": 0.42, "fixed_duration": 5, "show_icons": True,
    "event_filter": "全部类型",
    "screens": "所有屏幕", "reduce_motion": False,
}
CHOICES = {
    "style": {"胶囊", "轻盈", "纯文字"},
    "font_family": {"苹方", "系统", "冬青", "宋体", "华文黑体"},
    "region": {"顶部", "中部", "底部"},
    "motion": {"滚动", "固定停留"},
    "event_filter": {"全部类型", "隐藏工作", "只看需处理"},
    "screens": {"所有屏幕", "主屏幕"},
    "content": {"简洁摘要", "部分详情"},
    "progress": {"精简", "全部"},
}
RANGES = {"font_size": (12, 22), "speed": (0.5, 2.0),
          "opacity": (0.4, 1.0), "spacing": (42, 80),
          "density": (1, 12), "coverage": (0.2, 0.8), "fixed_duration": (2, 10),
          "outline_width": (0.5, 1.5)}
LEGACY_COLORS = {"白色": "#FFFFFF", "黑色": "#141A26", "暖黄": "#FFE073", "青色": "#8CF0FF"}
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def sanitize_settings(saved):
    result = DEFAULT_SETTINGS.copy()
    if not isinstance(saved, dict):
        return result
    for key, allowed in CHOICES.items():
        value = saved.get(key)
        if isinstance(value, str) and value in allowed:
            result[key] = value
    for key, (low, high) in RANGES.items():
        value = saved.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
            result[key] = value
    for key in ("text_color", "outline_color"):
        color = saved.get(key)
        if isinstance(color, str) and color in LEGACY_COLORS:
            color = LEGACY_COLORS[color]
        if isinstance(color, str) and COLOR_PATTERN.fullmatch(color):
            result[key] = color.upper()
    if type(saved.get("outline_enabled")) is bool:
        result["outline_enabled"] = saved["outline_enabled"]
    if type(saved.get("show_icons")) is bool:
        result["show_icons"] = saved["show_icons"]
    if type(saved.get("reduce_motion")) is bool:
        result["reduce_motion"] = saved["reduce_motion"]
    return result


def load_settings(path=SETTINGS_PATH, legacy_path=LEGACY_PATH):
    if path == SETTINGS_PATH:
        migrate_user_data()
    source = path if path.exists() else legacy_path
    try:
        saved = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return DEFAULT_SETTINGS.copy()
    result = sanitize_settings(saved)
    if source == legacy_path and path != legacy_path:
        try:
            save_settings(result, path)
        except OSError:
            pass
    return result


def save_settings(settings, path=SETTINGS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(sanitize_settings(settings), ensure_ascii=False, indent=2) + "\n"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".settings.", delete=False) as temp:
            temp.write(content)
            temp_path = Path(temp.name)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
