"""Opt-in, reversible user-level hook installation for supported agents."""

import argparse
import json
import os
import shlex
import re
import sys
import tempfile
from pathlib import Path

CODEX_EVENTS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PermissionRequest", "SubagentStart", "SubagentStop", "Stop",
    "Interrupt", "SessionEnd",
]
COMMON_EVENTS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "PermissionRequest", "Notification",
    "SubagentStart", "SubagentStop", "Stop", "StopFailure", "SessionEnd",
]
EVENTS = {"codex": CODEX_EVENTS, "claude-code": COMMON_EVENTS, "codebuddy": COMMON_EVENTS}
CONFIG_PATHS = {
    "codex": Path.home() / ".codex" / "hooks.json",
    "claude-code": Path.home() / ".claude" / "settings.json",
    "codebuddy": Path.home() / ".codebuddy" / "settings.json",
}
EMITTER_PATH = Path(__file__).resolve().parents[1] / "bin" / "agent-barrage-emit"


def command_for(agent):
    if getattr(sys, "frozen", False):
        return f"{shlex.quote(sys.executable)} --hook-adapter {agent}"
    source_checkout = EMITTER_PATH.parents[1] / "demo" / "run.sh"
    if EMITTER_PATH.is_file() and source_checkout.is_file():
        return f"/usr/bin/env python3 {shlex.quote(str(EMITTER_PATH))} --adapter {agent}"
    return f"{shlex.quote(sys.executable)} -m agent_barrage.emit --adapter {agent}"


def is_our_handler(handler, agent):
    if not isinstance(handler, dict):
        return False
    command = handler.get("command", "")
    if not isinstance(command, str):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if len(parts) == 3 and parts[1:] == ["--hook-adapter", agent]:
        return Path(parts[0]).name == "AgentBarrage"
    if len(parts) != 5:
        return False
    source_command = (parts[0] == "/usr/bin/env" and parts[1] == "python3"
                      and Path(parts[2]).name == "agent-barrage-emit")
    installed_command = (bool(re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(parts[0]).name))
                         and parts[1:3] == ["-m", "agent_barrage.emit"])
    return (source_command or installed_command) and parts[3:] == ["--adapter", agent]


def update_config(config, agent, uninstall=False):
    if agent not in EVENTS:
        raise ValueError("unsupported agent")
    if not isinstance(config, dict):
        raise ValueError("settings top level must be an object")
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings hooks must be an object")
    command = command_for(agent)
    for event in EVENTS[agent]:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"hooks.{event} must be a list")
        cleaned = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                cleaned.append(group)
                continue
            handlers = [handler for handler in group["hooks"] if not is_our_handler(handler, agent)]
            if handlers:
                cleaned.append({**group, "hooks": handlers})
        if not uninstall:
            handler = {"type": "command", "command": command, "timeout": 2}
            if agent == "codex" and event not in {"SessionEnd", "Interrupt"}:
                handler["async"] = True
            if event in {"SessionEnd", "Interrupt"}:
                handler["timeout"] = 1
            cleaned.append({"hooks": [handler]})
        if cleaned:
            hooks[event] = cleaned
        else:
            hooks.pop(event, None)
    if not hooks:
        config.pop("hooks", None)
    return config


def atomic_save(path, content):
    if path.is_symlink():
        raise OSError(f"refusing to replace symlinked settings: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + ".agentbarrage-backup")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
            os.chmod(backup, 0o600)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".agentbarrage.", delete=False) as temp:
        temp.write(content)
        temp_path = Path(temp.name)
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, path)


def read_config(agent):
    if agent not in EVENTS:
        raise ValueError("unsupported agent")
    path = CONFIG_PATHS[agent]
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def integration_status(agent):
    """Count only AgentBarrage-owned handlers in one tool's config."""
    config = read_config(agent)
    hooks = config.get("hooks", {}) if isinstance(config, dict) else {}
    if not isinstance(hooks, dict):
        raise ValueError("settings hooks must be an object")
    count = 0
    for event in EVENTS[agent]:
        for group in hooks.get(event, []):
            if isinstance(group, dict):
                count += sum(is_our_handler(handler, agent) for handler in group.get("hooks", []))
    return count, len(EVENTS[agent])


def apply_agent(agent, uninstall=False):
    path = CONFIG_PATHS[agent]
    updated = update_config(read_config(agent), agent, uninstall)
    atomic_save(path, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=sorted(EVENTS), required=True)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    path = CONFIG_PATHS[args.agent]
    if args.dry_run:
        update_config(read_config(args.agent), args.agent, args.uninstall)
        print(f"Config: {path}\nCommand: {command_for(args.agent)}")
        print(f"Events ({len(EVENTS[args.agent])}): {', '.join(EVENTS[args.agent])}")
        print("Action: remove AgentBarrage handlers" if args.uninstall else "Action: add AgentBarrage handlers")
        return 0
    apply_agent(args.agent, args.uninstall)
    print(f"{'Removed' if args.uninstall else 'Installed'} {args.agent} hooks: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
