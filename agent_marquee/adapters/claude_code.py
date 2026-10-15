"""Claude Code command hook adapter; uses only event metadata."""

from agent_marquee.core.events import make_event, with_detail
from .details import tool_detail


def normalize(payload):
    if not isinstance(payload, dict):
        return None
    event = payload.get("hook_event_name")
    kind = "working"
    if event == "SessionStart":
        message = "会话已开始或恢复"
    elif event == "UserPromptSubmit":
        message = "收到新任务"
    elif event == "PreToolUse":
        message = "正在使用工具"
    elif event == "PostToolUse":
        message = "工具操作已完成"
    elif event == "PostToolUseFailure":
        message, kind = "工具操作失败，请查看任务", "error"
    elif event == "PermissionRequest":
        message, kind = "需要查看 Claude Code", "attention"
    elif event == "Notification":
        message = "有一条新通知"
    elif event == "SubagentStart":
        message = "子任务已开始"
    elif event == "SubagentStop":
        message, kind = "子任务已结束", "success"
    elif event == "Stop":
        message, kind = "任务已完成，可以查看结果", "success"
    elif event == "StopFailure":
        message, kind = "任务因错误停止", "error"
    elif event == "SessionEnd":
        message = "会话已结束"
    else:
        return None
    result = make_event("claude-code", event, kind, message, payload.get("cwd"),
                        payload.get("session_id"), payload.get("turn_id"))
    return with_detail(result, tool_detail(payload) if event in {"PreToolUse", "PostToolUse"} else "")
