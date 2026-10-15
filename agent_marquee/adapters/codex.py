"""Codex lifecycle hook adapter."""

from agent_marquee.core.events import make_event, with_detail
from .details import tool_detail

TOOL_LABELS = {"Bash": "运行命令", "apply_patch": "编辑文件", "Agent": "处理子任务"}


def tool_label(name):
    if name in TOOL_LABELS:
        return TOOL_LABELS[name]
    if isinstance(name, str) and name.startswith("mcp__"):
        return "调用外部工具"
    return "使用工具"


def normalize(payload):
    if not isinstance(payload, dict):
        return None
    event = payload.get("hook_event_name")
    label = tool_label(payload.get("tool_name"))
    kind = "working"
    if event == "SessionStart":
        message = "会话已恢复" if payload.get("source") == "resume" else "会话已开始"
    elif event == "UserPromptSubmit":
        message = "收到新任务"
    elif event == "PreToolUse":
        message = f"正在{label}"
    elif event == "PostToolUse":
        response = payload.get("tool_response")
        exit_code = response.get("exit_code", response.get("exitCode")) if isinstance(response, dict) else None
        if isinstance(exit_code, int) and exit_code != 0:
            message, kind = f"{label}失败，请查看任务", "error"
        else:
            message = f"{label}已结束"
    elif event == "PermissionRequest":
        message, kind = "需要批准操作", "attention"
    elif event == "SubagentStart":
        message = "子任务已开始"
    elif event == "SubagentStop":
        message, kind = "子任务已结束", "success"
    elif event == "Stop":
        message, kind = "任务已完成，可以查看结果", "success"
    elif event == "Interrupt":
        message, kind = "任务已中断", "attention"
    elif event == "SessionEnd":
        message = "会话已结束"
    else:
        return None
    result = make_event("codex", event, kind, message, payload.get("cwd"),
                        payload.get("session_id"), payload.get("turn_id"))
    return with_detail(result, tool_detail(payload) if event in {"PreToolUse", "PostToolUse"} else "")
