"""Small allowlisted details for opt-in on-screen display."""

import re
from pathlib import Path

from agent_marquee.core.events import short_text

SAFE_PROGRAMS = {"python", "python3", "git", "npm", "pnpm", "yarn", "pytest", "rg", "swift", "xcodebuild", "make"}
FILE_TOOLS = {"Write", "Edit", "Read", "write_to_file", "replace_in_file", "read_file"}


def _basename(value):
    if not isinstance(value, str):
        return ""
    name = Path(value).name
    return short_text(name, 36) if name and name not in {".", ".."} else ""


def tool_detail(payload):
    """Use only known metadata; never expose commands, arguments or output."""
    if not isinstance(payload, dict):
        return ""
    tool = payload.get("tool_name")
    data = payload.get("tool_input")
    if not isinstance(data, dict):
        return ""
    if tool in FILE_TOOLS:
        return _basename(data.get("file_path") or data.get("path"))
    if tool == "apply_patch":
        command = data.get("command")
        if isinstance(command, str):
            match = re.search(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", command, re.MULTILINE)
            return _basename(match.group(1).strip()) if match else ""
    if tool in {"Bash", "execute_command"}:
        command = data.get("command")
        if isinstance(command, str):
            first = command.strip().split(maxsplit=1)[0] if command.strip() else ""
            program = Path(first).name
            return program if program in SAFE_PROGRAMS else ""
    return ""
