"""Opt-in, token-protected localhost ingress for automation clients."""

import argparse
import hmac
import json
import os
import secrets
import stat
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core.events import KINDS, make_event, with_detail
from .core.sources import SOURCES_PATH, SourceRegistry
from .core.spool import publish

TOKEN_PATH = SOURCES_PATH.with_name("bridge-token")
MAX_BODY_BYTES = 4096


def load_or_create_token(path=TOKEN_PATH):
    if path.is_symlink():
        raise OSError("拒绝读取符号链接形式的接口密钥")
    if path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise OSError("接口密钥权限必须为当前用户 0600")
        token = path.read_text(encoding="ascii").strip()
        if len(token) < 32:
            raise ValueError("现有接口密钥无效")
        return token
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(token + "\n")
    return token


def make_handler(token, registry, publisher=publish):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def respond(self, status, message):
            body = json.dumps({"status": message}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/v1/events":
                return self.respond(404, "not_found")
            authorization = self.headers.get("Authorization", "")
            if not hmac.compare_digest(authorization, f"Bearer {token}"):
                return self.respond(401, "unauthorized")
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                return self.respond(415, "json_required")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.respond(400, "bad_length")
            if not 0 < length <= MAX_BODY_BYTES:
                return self.respond(413, "body_too_large")
            try:
                payload = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                return self.respond(400, "invalid_json")
            if not isinstance(payload, dict):
                return self.respond(400, "invalid_event")
            agent = payload.get("agent")
            registry.refresh()
            if not isinstance(agent, str) or registry.display_name(agent) is None:
                return self.respond(422, "source_not_registered")
            if not registry.is_enabled(agent):
                return self.respond(403, "source_paused")
            kind = payload.get("kind")
            message = payload.get("message")
            if not isinstance(kind, str) or kind not in KINDS or not isinstance(message, str) or not 1 <= len(message) <= 120:
                return self.respond(422, "invalid_event")
            event_name = payload.get("event", "custom")
            project = payload.get("project", "对话")
            detail = payload.get("detail", "")
            open_url = payload.get("open_url", "")
            if not isinstance(event_name, str) or not 1 <= len(event_name) <= 60 or not isinstance(project, str):
                return self.respond(422, "invalid_event")
            if not isinstance(detail, str) or len(detail) > 48:
                return self.respond(422, "invalid_event")
            try:
                event = make_event(agent, event_name, kind, message, project, open_url=open_url)
                with_detail(event, detail)
            except ValueError:
                return self.respond(422, "invalid_event")
            accepted = publisher(event)
            return self.respond(202 if accepted else 503, "accepted" if accepted else "unavailable")

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--show-token", action="store_true", help="print the local bridge token once")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    token = load_or_create_token()
    if args.show_token:
        print(f"Token: {token}")
    print(f"AgentBarrage bridge listening on http://127.0.0.1:{args.port}/v1/events", flush=True)
    registry = SourceRegistry()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(token, registry))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
