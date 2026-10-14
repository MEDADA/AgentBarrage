"""Public CLI for sending a safe, explicit event from any local tool."""

import argparse

from .core.events import KINDS, make_event, with_detail
from .core.spool import publish


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, help="Lowercase source id, such as my-agent")
    parser.add_argument("--event", default="custom")
    parser.add_argument("--kind", required=True, choices=sorted(KINDS))
    parser.add_argument("--message", required=True, help="Short text safe to show over other windows")
    parser.add_argument("--detail", default="", help="Optional short excerpt, shown only in partial-detail mode")
    parser.add_argument("--project", default="未命名项目")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--url", default="", help="Optional http(s) link to the source task")
    args = parser.parse_args(argv)
    event = make_event(args.agent, args.event, args.kind, args.message,
                       args.project, args.session_id, open_url=args.url)
    with_detail(event, args.detail)
    if not publish(event):
        parser.error("could not publish local event")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
