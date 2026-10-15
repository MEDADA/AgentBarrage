"""Agent independent event ingress. Agent hooks pass JSON on stdin."""

import argparse
import json
import sys

from agent_marquee.adapters import claude_code, codebuddy, codex
from agent_marquee.core.spool import publish

NORMALIZERS = {
    "codex": codex.normalize,
    "claude-code": claude_code.normalize,
    "codebuddy": codebuddy.normalize,
}
MAX_INPUT_BYTES = 256 * 1024


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", choices=sorted(NORMALIZERS), required=True)
    args = parser.parse_args(argv)
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    payload = None
    if len(raw) <= MAX_INPUT_BYTES:
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            pass
    event = NORMALIZERS[args.adapter](payload)
    if event:
        publish(event)
    # Codex Stop expects JSON output; no adapter may make a control decision.
    if args.adapter == "codex" and isinstance(payload, dict) and payload.get("hook_event_name") == "Stop":
        sys.stdout.write("{}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
