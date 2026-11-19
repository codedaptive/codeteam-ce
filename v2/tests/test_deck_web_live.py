"""HTTP integration tests against a loopback server and a fake collector."""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from conftest import integration_only

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeCollector:
    def __init__(self):
        self.scans = 0

    def latest(self):
        return {"teams": [{"name": "alpha"}]}, [{"text": "warning"}]

    def disk_now(self):
        self.scans += 1


@integration_only
class LiveServerTests(unittest.TestCase):
    def setUp(self):
        from codeteam2.deck.server.build_server import build_server

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "index.html").write_text('<html data-motion="{{motion}}" data-interval="{{interval}}"></html>')
        (root / "deck.css").write_text("body { color: red; }")
        env = patch.dict(os.environ, {"CODETEAM_DECK_LOG": str(root / "deck.log")})
        env.start()
        self.addCleanup(env.stop)
        self.collector = FakeCollector()
        self.server = build_server(self.collector, port=0, web_dir=root, motion_on=True, interval=2.0)
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_binds_only_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_page_is_rendered_html_with_security_headers(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b'data-motion="on"', body)
        self.assertIn(b'data-interval="2.0"', body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Content-Security-Policy"],
                         "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'none'")

    def test_snapshot_contains_alert_log(self):
        status, headers, body = self.request("GET", "/snapshot.json")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(json.loads(body), {"teams": [{"name": "alpha"}], "alert_log": [{"text": "warning"}]})

    def test_untrusted_host_is_forbidden(self):
        status, _, _ = self.request("GET", "/", {"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)

    def test_disk_now_without_origin_is_forbidden(self):
        status, _, _ = self.request("POST", "/disk-now")
        self.assertEqual(status, 403)
        self.assertEqual(self.collector.scans, 0)

    def test_disk_now_cross_origin_is_forbidden(self):
        status, _, _ = self.request("POST", "/disk-now", {"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.collector.scans, 0)

    def test_disk_now_same_origin_is_accepted_once(self):
        status, _, body = self.request("POST", "/disk-now", {"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 204)
        self.assertEqual(body, b"")
        self.assertEqual(self.collector.scans, 1)

    def test_unknown_path_is_not_found(self):
        status, _, _ = self.request("GET", "/nope")
        self.assertEqual(status, 404)

    def test_template_is_not_served_as_static_file(self):
        status, _, _ = self.request("GET", "/index.html")
        self.assertEqual(status, 404)

    def test_static_css_is_served_with_content_type(self):
        status, headers, body = self.request("GET", "/deck.css")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/css"))
        self.assertEqual(body, b"body { color: red; }")


@integration_only
class LiveFileLookupTests(unittest.TestCase):
    def setUp(self):
        from codeteam2.deck.server.build_server import build_server

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.web = root / "web"
        self.web.mkdir()
        (self.web / "js").mkdir()
        (self.web / "index.html").write_text("<html></html>")
        (self.web / "js" / "removed.js").write_bytes(b"before deletion();")
        (self.web / "notes.txt").write_text("private notes")
        (root / "outside.js").write_bytes(b"outside();")
        (self.web / "js" / "link.js").symlink_to(root / "outside.js")
        env = patch.dict(os.environ, {"CODETEAM_DECK_LOG": str(root / "deck.log")})
        env.start()
        self.addCleanup(env.stop)
        self.server = build_server(FakeCollector(), port=0, web_dir=self.web, motion_on=False, interval=2.0)
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, path):
        try:
            return LiveServerTests.request(self, "GET", path)
        except http.client.RemoteDisconnected:
            return None, {}, b""

    def test_javascript_added_after_start_is_served(self):
        (self.web / "js" / "late.js").write_bytes(b"late module();")
        status, _, body = self.request("/js/late.js")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"late module();")

    def test_served_file_deleted_after_start_is_not_found(self):
        status, _, body = self.request("/js/removed.js")
        self.assertEqual((status, body), (200, b"before deletion();"))
        (self.web / "js" / "removed.js").unlink()
        status, _, _ = self.request("/js/removed.js")
        self.assertEqual(status, 404)

    def test_symlink_to_javascript_outside_web_folder_is_not_found(self):
        self.assertEqual(self.request("/js/link.js")[0], 404)

    def test_disallowed_text_file_is_not_found(self):
        self.assertEqual(self.request("/notes.txt")[0], 404)

    def test_parent_path_to_javascript_outside_web_folder_is_not_found(self):
        self.assertEqual(self.request("/../outside.js")[0], 404)


@integration_only
class PortZeroTests(unittest.TestCase):
    def test_port_zero_prints_the_port_the_server_bound(self):
        # codeteam-jj S-12: --port 0 printed http://127.0.0.1:0/ while the server listened on a free port (D441)
        from http.server import ThreadingHTTPServer

        from codeteam2.deck.server import serve as serve_module

        class StillCollector:
            def __init__(self, *args):
                pass

            def run(self):
                pass

            def stop(self):
                pass

        bound = []

        def serve_once(server, *args, **kwargs):
            bound.append(server.server_address[1])
            raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as tmp, patch.object(serve_module, "Collector", StillCollector), \
                patch.object(ThreadingHTTPServer, "serve_forever", serve_once):
            lines = []
            result = serve_module.serve([], port=0, interval=2.0, thresholds=None, motion_on=False,
                                        out=lines.append, web_dir=Path(tmp))
        self.assertEqual(result, 0)
        self.assertNotEqual(bound, [0])
        self.assertEqual(lines, [f"http://127.0.0.1:{bound[0]}/"])


@integration_only
class BusyPortTests(unittest.TestCase):
    def test_listening_port_returns_one_line_naming_port_option(self):
        from codeteam2.deck.server.serve import serve

        with tempfile.TemporaryDirectory() as tmp, socket.socket() as held:
            held.bind(("127.0.0.1", 0))
            held.listen()
            port = held.getsockname()[1]
            lines = []
            with patch.dict(os.environ, {"CODETEAM_DECK_LOG": str(Path(tmp) / "deck.log")}):
                result = serve([], port=port, interval=2.0, thresholds=None, motion_on=False,
                               out=lines.append, web_dir=Path(tmp))
            self.assertEqual(result, 1)
            self.assertEqual(lines, [f"codeteam2 deck: port {port} is busy; choose another with --port"])

    def test_port_held_on_every_address_returns_one_line_naming_port_option(self):
        from codeteam2.deck.server.serve import serve

        with tempfile.TemporaryDirectory() as tmp, socket.socket() as held:
            held.bind(("0.0.0.0", 0))
            held.listen()
            port = held.getsockname()[1]
            lines = []
            with patch.dict(os.environ, {"CODETEAM_DECK_LOG": str(Path(tmp) / "deck.log")}):
                result = serve([], port=port, interval=2.0, thresholds=None, motion_on=False,
                               out=lines.append, web_dir=Path(tmp))
            self.assertEqual(result, 1)
            self.assertEqual(lines, [f"codeteam2 deck: port {port} is busy; choose another with --port"])
