"""Compatibility module for hooks installed before the AgentMarquee rename."""

from agent_marquee.emit import main

if __name__ == "__main__":
    raise SystemExit(main())
