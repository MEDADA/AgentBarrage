"""Small, versioned event envelope. Raw agent payloads never cross this boundary."""

import time
import re
import math
from pathlib import Path
from urllib.parse import urlsplit

VERSION = 1
KINDS = {"working", "success", "attention", "error"}
AGENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def valid_agent(agent):
    return isinstance(agent, str) and bool(AGENT_PATTERN.fullmatch(agent))


def short_text(value, limit):
    return " ".join(str(value).split())[:limit]


def project_name(cwd):
    if not isinstance(cwd, str) or not cwd:
        return "未命名项目"
    name = Path(cwd).name.replace("\n", " ").replace("\r", " ").strip()
    return name[:28] or "未命名项目"


def valid_open_url(value):
    if (not isinstance(value, str) or len(value) > 512
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
        return False
    if not value:
        return True
    try:
        parsed = urlsplit(value)
        parsed.port
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def make_event(agent, event, kind, message, cwd=None, session_id=None, turn_id=None, open_url=""):
    if not valid_agent(agent) or kind not in KINDS:
        raise ValueError("unsupported agent or event kind")
    if not valid_open_url(open_url):
        raise ValueError("source URL must be an http(s) link without credentials")
    result = {
        "version": VERSION,
        "agent": agent,
        "event": short_text(event, 60),
        "kind": kind,
        "message": short_text(message, 120),
        "project": project_name(cwd),
        "session_id": short_text(session_id or "", 100),
        "turn_id": short_text(turn_id or "", 100),
        "occurred_at": time.time(),
    }
    if open_url:
        result["open_url"] = open_url
    return result


def with_detail(event, detail):
    """Attach a short, adapter-approved hint; never pass raw tool input here."""
    if isinstance(detail, str) and detail:
        event["detail"] = short_text(detail, 48)
    return event


def valid_event(data):
    return (isinstance(data, dict)
            and type(data.get("version")) is int and data["version"] == VERSION
            and valid_agent(data.get("agent"))
            and isinstance(data.get("kind"), str) and data["kind"] in KINDS
            and isinstance(data.get("event"), str)
            and isinstance(data.get("message"), str)
            and isinstance(data.get("project"), str)
            and isinstance(data.get("detail", ""), str)
            and valid_open_url(data.get("open_url", ""))
            and isinstance(data.get("session_id"), str)
            and isinstance(data.get("turn_id"), str)
            and type(data.get("occurred_at")) in {int, float}
            and math.isfinite(data["occurred_at"])
            and 0 < len(data["event"]) <= 60
            and len(data["message"]) <= 120
            and len(data["project"]) <= 28
            and len(data.get("detail", "")) <= 48
            and len(data["session_id"]) <= 100
            and len(data["turn_id"]) <= 100)
