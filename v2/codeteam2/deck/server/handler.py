"""The request handler: route() decides, this class answers."""
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .. import app
from .page_html import page_html
from .route import route
from .snapshot_payload import snapshot_payload
from .web_files import web_files

CONTENT_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".html": "text/html; charset=utf-8"}
# The page loads only its own files and fetches only this server; inline styles are allowed for the bars' widths.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def make_handler(collector, web_dir: Path, motion_on: bool, interval: float) -> type[BaseHTTPRequestHandler]:
    """A handler class bound to one collector and web folder. Each request lists the web folder afresh, so a page
    file added while the server runs is served and a removed one is a 404."""

    class DeckHandler(BaseHTTPRequestHandler):
        def _answer(self):
            try:
                self._dispatch()
            except Exception:  # a bad request is logged; the server keeps serving
                app._log(traceback.format_exc())

        def _dispatch(self):
            files = web_files(web_dir)
            status, action, arg = route(self.command, self.path, self.headers, self.server.server_address[1], files)
            if action in ("page", "static"):
                self._send_file(status, action, files.get(arg))
            elif action == "snapshot":
                self._send(status, "application/json", snapshot_payload(*collector.latest()))
            elif action == "disk_now":
                collector.disk_now()
                self._send(status, None, b"")
            else:
                self._refuse(status)

        def _send_file(self, status, action, path):
            """A page or static file; 404 when it is not in this request's listing or is gone by the time it is read."""
            if path is None:
                return self._refuse(404)
            try:
                if action == "page":
                    content_type = CONTENT_TYPES[".html"]
                    body = page_html(path.read_text(), motion_on, interval).encode("utf-8")
                else:
                    content_type, body = CONTENT_TYPES[path.suffix], path.read_bytes()
            except FileNotFoundError:
                return self._refuse(404)
            self._send(status, content_type, body)

        def _refuse(self, status):
            self._send(status, "text/plain; charset=utf-8", HTTPStatus(status).phrase.encode("utf-8"))

        def _send(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            if content_type:
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _answer

        def log_message(self, format, *args):
            """Silent: a request writes nothing to stderr."""

    return DeckHandler
