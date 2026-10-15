"""Copy user data from the former AgentBarrage support directory once."""

import os
import shutil
import stat
import tempfile
from pathlib import Path

SUPPORT_ROOT = Path.home() / "Library" / "Application Support"
DATA_DIR = SUPPORT_ROOT / "AgentMarquee"
LEGACY_DATA_DIR = SUPPORT_ROOT / "AgentBarrage"
DATA_FILES = ("settings.json", "sources.json", "bridge-token")
ICON_SUFFIXES = {".png", ".jpg", ".jpeg", ".icns"}


def _safe_file(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()


def _copy_once(source, target):
    if target.exists() or target.is_symlink() or not _safe_file(source):
        return
    if target.parent.is_symlink():
        raise OSError(f"拒绝写入符号链接目录: {target.parent}")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=target.parent, prefix=".migration.", delete=False) as output:
            temporary = Path(output.name)
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
        os.chmod(temporary, 0o600)
        if not target.exists() and not target.is_symlink():
            os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def migrate_user_data():
    """Preserve old data while moving active reads to the new support directory."""
    if LEGACY_DATA_DIR.is_symlink() or not LEGACY_DATA_DIR.is_dir():
        return
    if DATA_DIR.is_symlink():
        raise OSError(f"拒绝写入符号链接目录: {DATA_DIR}")
    for name in DATA_FILES:
        _copy_once(LEGACY_DATA_DIR / name, DATA_DIR / name)
    icon_dir = LEGACY_DATA_DIR / "icons"
    if icon_dir.is_symlink() or not icon_dir.is_dir():
        return
    for icon in icon_dir.iterdir():
        if icon.suffix.lower() in ICON_SUFFIXES:
            _copy_once(icon, DATA_DIR / "icons" / icon.name)
