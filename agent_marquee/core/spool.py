"""File-based local event transport; works in restricted agent sandboxes."""

import json
import os
import random
import stat
import time
import uuid
from pathlib import Path

from .events import valid_event
from .event_v2 import valid_event_v2

# Keep the transport directory stable for already installed hook processes.
SPOOL_DIR = Path(f"/tmp/agentbarrage-{os.getuid()}")
MAX_EVENT_BYTES = 4096
MAX_AGE_SECONDS = 45
MAX_PENDING_FILES = 500


def ensure_spool():
    SPOOL_DIR.mkdir(mode=0o700, exist_ok=True)
    info = SPOOL_DIR.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("unsafe AgentMarquee spool directory")
    os.chmod(SPOOL_DIR, 0o700)


def publish(event):
    if not (valid_event(event) or valid_event_v2(event)):
        return False
    data = json.dumps(event, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_EVENT_BYTES:
        return False
    try:
        ensure_spool()
        name = f"{time.time_ns()}-{uuid.uuid4().hex}"
        temp = SPOOL_DIR / f".{name}.tmp"
        final = SPOOL_DIR / f"{name}.json"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temp, final)
        if random.randrange(20) == 0:
            prune()
        return True
    except OSError:
        return False


def prune():
    """Bound disk use while the overlay is closed; best effort in hook processes."""
    try:
        paths = sorted(SPOOL_DIR.glob("*.json"))
        now = time.time()
        for path in paths[:-MAX_PENDING_FILES]:
            path.unlink(missing_ok=True)
        for path in paths[-MAX_PENDING_FILES:]:
            if now - path.stat().st_mtime > MAX_AGE_SECONDS:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def drain(limit=30):
    try:
        ensure_spool()
        paths = sorted(SPOOL_DIR.glob("*.json"))[:limit]
    except OSError:
        return []
    events = []
    for path in paths:
        try:
            info = path.stat()
            now = time.time()
            if (info.st_size > MAX_EVENT_BYTES
                    or abs(now - info.st_mtime) > MAX_AGE_SECONDS):
                continue
            event = json.loads(path.read_text(encoding="utf-8"))
            if ((valid_event(event) or valid_event_v2(event))
                    and abs(now - event.get("occurred_at", 0)) <= MAX_AGE_SECONDS):
                events.append(event)
        except (OSError, ValueError, TypeError):
            pass
        finally:
            try:
                path.unlink()
            except OSError:
                pass
    return events
