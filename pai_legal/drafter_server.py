"""A loopback-only web server that hands the drafter its brief.

Exporting a file and asking the user to find it again is a step a
self-represented person does not need. If PAi Legal serves the page, it can
serve the brief with it: export, the browser opens, the case is already
loaded.

## What this deliberately does not do

**Binds to 127.0.0.1, never 0.0.0.0.** The second would expose case files to
every device on the network - office LAN, coffee shop wifi. One character, and
the difference between a local tool and a data leak.

**Sends no Access-Control-Allow-Origin header.** Any page open in the browser
can attempt a request to localhost. Without that header the same-origin policy
stops it reading the response, so the absence of a line is the protection here.

**Requires a per-session token in the path.** That covers what CORS does not -
another process on the same machine, or a page that guesses the port. The
token is generated per run and never written to disk.

**Picks its own port.** 8000 is crowded; a collision would look like a broken
app rather than a busy port.

The server holds one brief at a time, in memory, and stops when the app does.
"""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple

LOOPBACK = "127.0.0.1"


class DrafterServer:
    """Serves the drafter page and exactly one brief, to this machine only."""

    def __init__(self, page: Path):
        self.page = Path(page)
        self.token = secrets.token_urlsafe(24)
        self._brief: str = ""
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle

    def start(self) -> Tuple[str, int]:
        if self._server is not None:
            return LOOPBACK, self._server.server_port
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:
                # A request log of case-file fetches is not worth keeping.
                return

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                # No Access-Control-Allow-Origin: another site must not be able
                # to read this. Cache-Control keeps the brief out of the
                # browser's disk cache after the session.
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                    "connect-src 'self' https://api.anthropic.com https://api.openai.com; "
                    "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
                )
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802 - stdlib naming
                expected_host = f"{LOOPBACK}:{outer._server.server_port}"
                if self.headers.get("Host", "") != expected_host:
                    self._send(421, b"Misdirected request", "text/plain; charset=utf-8")
                    return
                path = self.path.split("?", 1)[0]
                if path in (f"/{outer.token}", f"/{outer.token}/"):
                    try:
                        body = outer.page.read_bytes()
                    except OSError:
                        self._send(500, b"Drafter page missing", "text/plain; charset=utf-8")
                        return
                    self._send(200, body, "text/html; charset=utf-8")
                    return
                if path == f"/{outer.token}/brief.json":
                    if not outer._brief:
                        self._send(404, b"{}", "application/json; charset=utf-8")
                        return
                    self._send(200, outer._brief.encode("utf-8"),
                               "application/json; charset=utf-8")
                    return
                # Anything else, including a guessed path, gets nothing useful.
                self._send(404, b"Not found", "text/plain; charset=utf-8")

        # Port 0 lets the OS choose a free one.
        self._server = ThreadingHTTPServer((LOOPBACK, 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return LOOPBACK, self._server.server_port

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
        self._server = None
        self._thread = None
        self._brief = ""

    # -- content

    def publish(self, brief: dict) -> str:
        """Hold a brief for the drafter and return the URL that opens it."""
        self._brief = json.dumps(brief, indent=2, ensure_ascii=False)
        host, port = self.start()
        return f"http://{host}:{port}/{self.token}"

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        return self._server.server_port if self._server else 0
