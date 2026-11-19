"""Detached cleaning uses a stand-in make, never a real zone-clean."""
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.start_zone_clean import start_zone_clean  # noqa: E402
from conftest import integration_module  # noqa: E402

pytestmark = integration_module


def _make(tmp_path, monkeypatch, body):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    executable = bindir / "make"
    executable.write_text("#!/bin/sh\n" + body)
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))


def _wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)
    return predicate()


def test_starts_make_with_tree_arguments_and_environment(tmp_path, monkeypatch):
    tree = tmp_path / "tree with spaces"
    tree.mkdir()
    home = tmp_path / "home with spaces"
    record = tmp_path / "record"
    monkeypatch.setenv("RECORD", str(record))
    monkeypatch.setenv("INHERITED_MARKER", "inherited")
    _make(tmp_path, monkeypatch, 'printf "%s\\n" "$@" "$PWD" "$MAKEFILES" "$CODETEAM_HOME" '
          '"$ZONE_CLEAN_KEEP_INDEX" "$INHERITED_MARKER" > "$RECORD"\n')

    assert start_zone_clean(tree, home) is True
    assert _wait_for(record.exists), "stand-in make did not write its record"
    assert record.read_text().splitlines() == [
        "--no-print-directory", "zone-clean", str(tree), str(home / "zone" / "zone.mk"),
        str(home), "1", "inherited",
    ]


def test_returns_before_make_finishes(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    tree.mkdir()
    entered, release, finished = (tmp_path / name for name in ("entered", "release", "finished"))
    monkeypatch.setenv("ENTERED", str(entered))
    monkeypatch.setenv("RELEASE", str(release))
    monkeypatch.setenv("FINISHED", str(finished))
    _make(tmp_path, monkeypatch, ': > "$ENTERED"\nwhile [ ! -e "$RELEASE" ]; do sleep 0.05; done\n'
          ': > "$FINISHED"\n')
    results = []
    returned = threading.Event()

    def invoke():
        try:
            results.append(start_zone_clean(tree, tmp_path / "home"))
        finally:
            returned.set()

    threading.Thread(target=invoke, daemon=True).start()
    try:
        assert _wait_for(entered.exists), "stand-in make did not start"
        assert returned.wait(10), "the call waited for make to finish"
        assert results == [True]
        assert not finished.exists()
    finally:
        release.touch()
        if entered.exists():
            _wait_for(finished.exists)


def test_missing_tree_returns_false(tmp_path, monkeypatch):
    record = tmp_path / "record"
    monkeypatch.setenv("RECORD", str(record))
    _make(tmp_path, monkeypatch, ': > "$RECORD"\n')
    assert start_zone_clean(tmp_path / "missing", tmp_path / "home") is False
    assert not record.exists()
