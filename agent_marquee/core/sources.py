"""User-defined display sources, independent of any one AI vendor."""

import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

from .events import valid_agent
from .migration import DATA_DIR, migrate_user_data

SOURCES_PATH = DATA_DIR / "sources.json"
BUILTIN_IDS = {"codex", "claude-code", "codebuddy"}
MAX_SOURCES = 50
ICON_SUFFIXES = {".png", ".jpg", ".jpeg", ".icns"}
MAX_ICON_BYTES = 2 * 1024 * 1024


def clean_name(name):
    if not isinstance(name, str):
        raise ValueError("显示名称必须是文字")
    value = " ".join(name.split())
    if not 1 <= len(value) <= 32:
        raise ValueError("显示名称需为 1–32 个字符")
    return value


def load_sources(path=SOURCES_PATH):
    if path == SOURCES_PATH:
        migrate_user_data()
    if path.is_symlink():
        raise OSError("拒绝读取符号链接形式的来源配置")
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("sources"), list):
        raise ValueError("来源配置格式无效")
    result = []
    seen = set()
    for item in data["sources"]:
        if not isinstance(item, dict) or not valid_agent(item.get("id")) or item["id"] in BUILTIN_IDS:
            raise ValueError("来源配置包含无效标识")
        if item["id"] in seen:
            raise ValueError("来源配置包含重复标识")
        seen.add(item["id"])
        enabled = item.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError("来源配置包含无效启用状态")
        icon = item.get("icon")
        if icon is not None and (not isinstance(icon, str) or
                                 not re.fullmatch(re.escape(item["id"]) + r"\.(png|jpg|jpeg|icns)", icon)):
            raise ValueError("来源配置包含无效图标")
        result.append({"id": item["id"], "name": clean_name(item.get("name")),
                       "enabled": enabled, "icon": icon})
    if len(result) > MAX_SOURCES:
        raise ValueError("自定义来源数量超过上限")
    return result


def save_sources(sources, path=SOURCES_PATH):
    if path.is_symlink():
        raise OSError("拒绝写入符号链接形式的来源配置")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps({"version": 1, "sources": sources}, ensure_ascii=False, indent=2) + "\n"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".sources.", delete=False) as temp:
            temp.write(content)
            temp_path = Path(temp.name)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def add_source(source_id, name, path=SOURCES_PATH):
    if not valid_agent(source_id) or source_id in BUILTIN_IDS:
        raise ValueError("标识需为小写字母、数字、连字符，且不能与内置工具重复")
    name = clean_name(name)
    sources = load_sources(path)
    if any(item["id"] == source_id for item in sources):
        raise ValueError("来源标识已存在")
    if len(sources) >= MAX_SOURCES:
        raise ValueError("最多添加 50 个自定义来源")
    sources.append({"id": source_id, "name": name, "enabled": True, "icon": None})
    save_sources(sources, path)
    return sources


def remove_source(source_id, path=SOURCES_PATH):
    sources = load_sources(path)
    removed = next((item for item in sources if item["id"] == source_id), None)
    updated = [item for item in sources if item["id"] != source_id]
    if len(updated) == len(sources):
        return sources
    save_sources(updated, path)
    if removed and removed["icon"]:
        (path.parent / "icons" / removed["icon"]).unlink(missing_ok=True)
    return updated


def set_source_icon(source_id, image_path, path=SOURCES_PATH):
    sources = load_sources(path)
    item = next((entry for entry in sources if entry["id"] == source_id), None)
    if item is None:
        raise ValueError("来源不存在")
    old_icon = item["icon"]
    if image_path is None:
        item["icon"] = None
        save_sources(sources, path)
        if old_icon:
            (path.parent / "icons" / old_icon).unlink(missing_ok=True)
        return sources
    image_path = Path(image_path)
    suffix = image_path.suffix.lower()
    if suffix not in ICON_SUFFIXES or image_path.is_symlink():
        raise ValueError("图标只支持 PNG、JPEG 或 ICNS 本地文件")
    info = image_path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_ICON_BYTES:
        raise ValueError("图标文件必须小于 2 MB")
    icon_dir = path.parent / "icons"
    icon_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if icon_dir.is_symlink():
        raise OSError("拒绝写入符号链接形式的图标目录")
    icon_name = source_id + suffix
    destination = icon_dir / icon_name
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=icon_dir, prefix=".icon.", delete=False) as output:
            temporary = Path(output.name)
            with image_path.open("rb") as source:
                shutil.copyfileobj(source, output)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        item["icon"] = icon_name
        save_sources(sources, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if old_icon and old_icon != icon_name:
        (icon_dir / old_icon).unlink(missing_ok=True)
    return sources


def set_source_enabled(source_id, enabled, path=SOURCES_PATH):
    if type(enabled) is not bool:
        raise ValueError("启用状态必须为布尔值")
    sources = load_sources(path)
    for item in sources:
        if item["id"] == source_id:
            item["enabled"] = enabled
            save_sources(sources, path)
            return sources
    raise ValueError("来源不存在")


class SourceRegistry:
    def __init__(self, path=SOURCES_PATH):
        self.path = path
        self._mtime = None
        self._sources = {}
        self.refresh(force=True)

    def refresh(self, force=False):
        try:
            mtime = self.path.stat().st_mtime_ns if self.path.exists() else None
            if force or mtime != self._mtime:
                self._sources = {item["id"]: item for item in load_sources(self.path)}
                self._mtime = mtime
        except (OSError, ValueError, TypeError):
            self._sources = {}
            self._mtime = None

    def display_name(self, source_id):
        item = self._sources.get(source_id)
        return item["name"] if item else None

    def is_enabled(self, source_id):
        item = self._sources.get(source_id)
        return item["enabled"] if item else True

    def icon_path(self, source_id):
        item = self._sources.get(source_id)
        return self.path.parent / "icons" / item["icon"] if item and item["icon"] else None
