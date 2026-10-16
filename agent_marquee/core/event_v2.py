"""Canonical observations. Lifecycle state is derived by a separate reducer."""

import hashlib
import json
import math
import re
import time
import uuid

from .events import KINDS, short_text, valid_agent, valid_event, valid_open_url

VERSION = 2
EVENT_TYPES = {
    "session_started", "session_ended", "prompt_submitted", "tool_started",
    "tool_finished", "tool_failed", "approval_requested", "approval_visible",
    "input_requested", "task_completed", "task_failed", "task_cancelled",
    "turn_stop_observed", "turn_interrupted", "turn_failed",
    "subagent_started", "subagent_finished", "notification", "custom",
}
ID_FIELDS = ("event_id", "source_instance", "session_id", "turn_id", "task_id",
             "parent_task_id", "trace_id")
ALLOWED_FIELDS = {
    "version", "agent", "event_type", "event_id", "occurred_at", "summary",
    "source_instance", "session_id", "turn_id", "task_id", "parent_task_id",
    "trace_id", "sequence", "project", "detail", "open_url",
    "presentation_kind", "source_event",
}


def make_event_v2(agent, event_type, summary, *, project="", session_id="",
                  turn_id="", task_id="", parent_task_id="", source_instance="",
                  trace_id="", sequence=None, occurred_at=None, event_id=None,
                  detail="", open_url="", presentation_kind="working", source_event=""):
    """Construct a bounded event from adapter-approved metadata only."""
    if any(not isinstance(value, str) for value in (summary, project, detail, source_event)):
        raise ValueError("display metadata must be text")
    event = {
        "version": VERSION,
        "agent": agent,
        "event_type": event_type,
        "event_id": event_id if event_id is not None else uuid.uuid4().hex,
        "occurred_at": time.time() if occurred_at is None else occurred_at,
        "summary": short_text(summary, 120),
        "source_instance": source_instance,
        "session_id": session_id,
        "turn_id": turn_id,
        "task_id": task_id,
        "parent_task_id": parent_task_id,
        "trace_id": trace_id,
        "sequence": sequence,
        "project": short_text(project, 28),
        "detail": short_text(detail, 48),
        "open_url": open_url,
        "presentation_kind": presentation_kind,
        "source_event": short_text(source_event, 60),
    }
    if not valid_event_v2(event):
        raise ValueError("invalid AgentMarquee v2 event")
    return event


def valid_event_v2(data):
    if not isinstance(data, dict) or set(data) - ALLOWED_FIELDS:
        return False
    if (type(data.get("version")) is not int or data["version"] != VERSION
            or not valid_agent(data.get("agent"))
            or not isinstance(data.get("event_type"), str)
            or data["event_type"] not in EVENT_TYPES
            or not isinstance(data.get("presentation_kind"), str)
            or data["presentation_kind"] not in KINDS
            or not valid_open_url(data.get("open_url", ""))):
        return False
    for field in ID_FIELDS:
        value = data.get(field, "")
        if (not isinstance(value, str) or len(value) > 100
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            return False
    if not data.get("event_id"):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", data["event_id"]):
        return False
    if "summary" not in data:
        return False
    for field, limit in (("summary", 120), ("project", 28), ("detail", 48),
                         ("source_event", 60)):
        value = data.get(field, "")
        if not isinstance(value, str) or len(value) > limit:
            return False
    occurred_at = data.get("occurred_at")
    if type(occurred_at) not in {int, float} or not math.isfinite(occurred_at):
        return False
    sequence = data.get("sequence")
    return sequence is None or (type(sequence) is int and sequence >= 0)


LEGACY_EVENT_TYPES = {
    "SessionStart": "session_started",
    "SessionEnd": "session_ended",
    "UserPromptSubmit": "prompt_submitted",
    "PreToolUse": "tool_started",
    "PostToolUse": "tool_finished",
    "PostToolUseFailure": "tool_failed",
    "PermissionRequest": "approval_requested",
    "SubagentStart": "subagent_started",
    "SubagentStop": "subagent_finished",
    "Stop": "turn_stop_observed",
    "StopFailure": "turn_failed",
    "Interrupt": "turn_interrupted",
    "Notification": "notification",
}


def from_v1(legacy):
    """Losslessly keep safe display fields, never infer a task outcome."""
    if not valid_event(legacy):
        raise ValueError("invalid AgentMarquee v1 event")
    safe = {key: legacy.get(key) for key in (
        "agent", "event", "kind", "message", "project", "session_id",
        "turn_id", "occurred_at", "detail", "open_url")}
    stable_id = hashlib.sha256(json.dumps(
        safe, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    event_type = LEGACY_EVENT_TYPES.get(legacy["event"], "custom")
    if legacy["event"] == "PostToolUse" and legacy["kind"] == "error":
        event_type = "tool_failed"
    return make_event_v2(
        legacy["agent"], event_type, legacy["message"],
        project=legacy["project"], session_id=legacy["session_id"],
        turn_id=legacy["turn_id"], occurred_at=legacy["occurred_at"],
        event_id=stable_id, detail=legacy.get("detail", ""),
        open_url=legacy.get("open_url", ""), presentation_kind=legacy["kind"],
        source_event=legacy["event"],
    )


def as_display_event(event):
    """Return the existing renderer fields without discarding the v2 source event."""
    if event.get("version") == 1:
        if not valid_event(event):
            raise ValueError("invalid AgentMarquee v1 event")
        return event
    if not valid_event_v2(event):
        raise ValueError("invalid AgentMarquee v2 event")
    return {
        "agent": event["agent"],
        "event": event.get("source_event") or event["event_type"],
        "kind": event["presentation_kind"],
        "message": event["summary"],
        "project": event.get("project", ""),
        "session_id": event.get("session_id", ""),
        "turn_id": event.get("turn_id", ""),
        "detail": event.get("detail", ""),
        "open_url": event.get("open_url", ""),
    }
