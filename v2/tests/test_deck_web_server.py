"""Unit tests for the deck web server; all collector dependencies are fakes."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class HostTests(unittest.TestCase):
    def test_host_allowed_exact_loopback_and_port(self):
        from codeteam2.deck.server.host_allowed import host_allowed

        for host, expected in [("127.0.0.1:8770", True), ("localhost:8770", True),
                               ("LOCALHOST:8770", True), (None, False),
                               ("localhost", False), ("localhost:9000", False),
                               ("evil.example:8770", False), ("localhost:8770.evil", False)]:
            with self.subTest(host=host):
                self.assertEqual(host_allowed(host, 8770), expected)

    def test_same_origin_exact_http_loopback_and_port(self):
        from codeteam2.deck.server.same_origin import same_origin

        for origin, expected in [("http://127.0.0.1:8770", True), ("http://LOCALHOST:8770", True),
                                 (None, False), ("null", False), ("https://localhost:8770", False),
                                 ("http://evil.example:8770", False), ("http://localhost:9000", False),
                                 ("http://localhost:8770/path", False)]:
            with self.subTest(origin=origin):
                self.assertEqual(same_origin(origin, 8770), expected)


class RouteTests(unittest.TestCase):
    def test_route_table(self):
        from codeteam2.deck.server.route import route

        host = {"Host": "localhost:8770"}
        origin = {"Host": "localhost:8770", "Origin": "http://localhost:8770"}
        evil = {"Host": "localhost:8770", "Origin": "http://evil.example"}
        cases = [
            ("GET", "/", {}, (403, "refuse", None)),
            ("GET", "/missing", {"Host": "evil.example:8770"}, (403, "refuse", None)),
            ("GET", "/?q=1#part", host, (200, "page", "index.html")),
            ("POST", "/", host, (405, "refuse", None)),
            ("GET", "/snapshot.json?x=1", host, (200, "snapshot", None)),
            ("POST", "/snapshot.json", host, (405, "refuse", None)),
            ("POST", "/disk-now", origin, (204, "disk_now", None)),
            ("POST", "/disk-now", host, (403, "refuse", None)),
            ("POST", "/disk-now", evil, (403, "refuse", None)),
            ("GET", "/disk-now", host, (405, "refuse", None)),
            ("GET", "/js/main.js#part", host, (200, "static", "js/main.js")),
            ("PUT", "/deck.css", host, (405, "refuse", None)),
            ("GET", "/index.html", host, (404, "refuse", None)),
            ("GET", "/../secret", host, (404, "refuse", None)),
            ("GET", "/missing", host, (404, "refuse", None)),
        ]
        for method, path, headers, expected in cases:
            with self.subTest(method=method, path=path, headers=headers):
                self.assertEqual(route(method, path, headers, 8770,
                                       {"index.html", "deck.css", "js/main.js"}), expected)


class PayloadTests(unittest.TestCase):
    def test_web_files_only_regular_allowed_suffixes(self):
        from codeteam2.deck.server.web_files import web_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "js").mkdir()
            for name in ("index.html", "deck.css", "js/main.js", "secret.json", "notes.txt"):
                (root / name).write_text("fixture")
            (root / "folder.css").mkdir()
            self.assertEqual(web_files(root), {"index.html": root / "index.html",
                                               "deck.css": root / "deck.css",
                                               "js/main.js": root / "js/main.js"})

    def test_page_html_replaces_motion_and_interval(self):
        from codeteam2.deck.server.page_html import page_html

        template = '<html data-motion="{{motion}}" data-interval="{{interval}}">{{motion}}</html>'
        self.assertEqual(page_html(template, True, 2.0),
                         '<html data-motion="on" data-interval="2.0">on</html>')
        self.assertEqual(page_html(template, False, 0.5),
                         '<html data-motion="off" data-interval="0.5">off</html>')

    def test_snapshot_payload_preserves_json_fixture_and_adds_alert_log(self):
        from codeteam2.deck.server.snapshot_payload import snapshot_payload

        fixture = json.loads((Path(__file__).parent / "deck_snapshot_golden.json").read_text())
        payload = json.loads(snapshot_payload(fixture, [{"text": "alert é"}]).decode("utf-8"))
        self.assertEqual(payload.pop("alert_log"), [{"text": "alert é"}])
        self.assertEqual(payload, fixture)


class FakeScanner:
    def __init__(self):
        self.roots = {}
        self.scans = 0

    def result(self):
        return {}

    def start(self):
        pass

    def scan_now(self):
        self.scans += 1


class FakeCollect:
    class Cache:
        pass

    def __init__(self):
        self.calls = 0
        self.fail = False

    def collect(self, names, *, cache, thresholds, disk):
        self.calls += 1
        if self.fail:
            raise ValueError("fake collect failed")
        return {"at": 100.0, "teams": [{"name": "alpha", "root": "/fake/root", "home": "/fake/home"}],
                "alerts": []}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        from codeteam2.deck.server.collector import Collector

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = Path(tmp.name) / "deck.log"
        env = patch.dict(os.environ, {"CODETEAM_DECK_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)
        self.now = 100.0
        self.scanner = FakeScanner()
        self.collect_mod = FakeCollect()
        self.collector = Collector(["alpha"], 2.0, None, collect_mod=self.collect_mod,
                                   scanner=self.scanner, clock=lambda: self.now)

    def test_first_tick_collects(self):
        self.assertTrue(self.collector.tick(100.0))
        self.assertEqual(self.collect_mod.calls, 1)
        self.assertEqual(self.collector.latest(100.0)[0]["teams"][0]["name"], "alpha")

    def test_latest_never_collects(self):
        self.assertEqual(self.collector.latest(100.0), ({}, []))
        self.assertEqual(self.collect_mod.calls, 0)
        self.collector.latest(101.0)
        self.assertEqual(self.collect_mod.calls, 0)

    def test_idle_at_thirty_seconds_clears_roots_without_collecting(self):
        self.collector.tick(100.0)
        self.assertEqual(self.scanner.roots, {"alpha": "/fake/root"})
        self.assertFalse(self.collector.tick(130.0))
        self.assertEqual(self.collect_mod.calls, 1)
        self.assertEqual(self.scanner.roots, {})

    def test_latest_after_idle_reactivates_next_tick(self):
        self.collector.tick(100.0)
        self.collector.tick(130.0)
        self.collector.latest(130.0)
        self.assertEqual(self.collect_mod.calls, 1)
        self.assertTrue(self.collector.tick(130.0))
        self.assertEqual(self.collect_mod.calls, 2)
        self.assertEqual(self.scanner.roots, {"alpha": "/fake/root"})

    def test_request_stamped_before_idle_but_arriving_after_idle_tick_wakes_collector(self):
        self.collector.tick(100.0)
        self.assertFalse(self.collector.tick(130.0))
        self.collector.latest(129.9)
        self.assertTrue(self.collector._wake.is_set())

    def test_failed_collect_keeps_previous_pair_and_logs(self):
        self.collector.tick(100.0)
        previous = self.collector.latest(100.0)
        self.collect_mod.fail = True
        self.collector.tick(101.0)
        self.assertEqual(self.collector.latest(101.0), previous)
        self.assertIn("fake collect failed", self.log.read_text())

    def test_disk_now_after_idle_runs_once_on_next_tick_and_restores_roots(self):
        self.collector.tick(100.0)
        self.collector.tick(130.0)
        self.now = 130.0
        self.collector.disk_now()
        self.assertEqual(self.scanner.scans, 0)
        self.assertTrue(self.collector.tick(130.0))
        self.assertEqual(self.scanner.roots, {"alpha": "/fake/root"})
        self.assertEqual(self.scanner.scans, 1)
        self.collector.tick(131.0)
        self.assertEqual(self.scanner.scans, 1)

    def test_run_logs_tick_exception(self):
        from codeteam2.deck import app

        def bad_follow(scanner, snap):
            self.collector.stop()
            raise RuntimeError("fake tick failed")

        with patch.object(app, "_follow_teams", side_effect=bad_follow):
            self.collector.run()
        self.assertIn("fake tick failed", self.log.read_text())


class AppTests(unittest.TestCase):
    def test_parse_web_default_port(self):
        from codeteam2.deck.app import _parse

        args = _parse(["--web"])
        self.assertTrue(args.web)
        self.assertEqual(args.port, 8770)

    def test_parse_explicit_port(self):
        from codeteam2.deck.app import _parse

        self.assertEqual(_parse(["--web", "--port", "9000"]).port, 9000)

    def test_main_web_passes_options_and_returns_serve_result(self):
        from codeteam2.deck.app import main
        from codeteam2.deck.server import serve as serve_module

        with patch.object(serve_module, "serve", return_value=17) as serve:
            self.assertEqual(main(["--web", "alpha", "--port", "9000", "--no-motion"]), 17)
        serve.assert_called_once_with(["alpha"], port=9000, interval=2.0, thresholds=None, motion_on=False)
