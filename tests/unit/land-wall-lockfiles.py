#!/usr/bin/env -S python3 -u
"""check_work_order lets a zone's work order carry a lock file the zone guard lets every lane edit, and still refuses
one the manifest's orchestrator_owns names (a Rust work order that adds a dependency edge
must commit the root Cargo.lock its build regenerates, and landing refused it as outside the zone). Unit: the
walls are a fake standing in for share/claude-hooks/lane_walls.py, and git is never run."""
import contextlib
import importlib.machinery
import importlib.util
import io
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_wall_lockfiles", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


class FakeWalls:
    """Answers owns_doc and lockfile, as lane_walls.Walls does, from the paths it is given."""

    def __init__(self, locks=(), docs=()):
        self.locks, self.docs = set(locks), set(docs)

    def owns_doc(self, f):
        return f in self.docs

    def lockfile(self, f):
        return f in self.locks


def check(files, walls):
    """check_work_order for zone acmex (apps/acmex) on a clean tree that changes `files`: the files it returns,
    or ("refused", exit code, the files its message lists)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = root / "sample.toml"
        manifest.write_text(f'repo = "{root / "repo"}"\nworktree_root = "{root / "team"}"\n'
                            '[[lanes]]\nname = "acmex"\npath = "apps/acmex"\n')
        team = cl.Team(manifest)
        rec = {"wo": "w", "zone": "acmex", "tree": tmp}
        err = io.StringIO()
        with patch.object(cl, "out", return_value=""), patch.object(cl, "work_order_files", return_value=files), \
                patch.object(cl, "zone_docs", return_value=[]), patch.object(cl, "guard_walls", return_value=walls), \
                contextlib.redirect_stderr(err):
            try:
                return cl.check_work_order(team, rec)
            except SystemExit as stop:
                listed = [line.strip() for line in err.getvalue().splitlines() if line.startswith("  ")]
                return ("refused", stop.code, listed)


def test_a_lock_file_the_walls_allow_lands_with_the_zones_change():
    files = ["apps/acmex/Cargo.toml", "Cargo.lock"]
    assert check(files, FakeWalls(locks={"Cargo.lock"})) == files


def test_a_lock_file_the_walls_do_not_allow_is_refused():
    # lockfile is False for a lock the manifest's orchestrator_owns names (gadget's Package.resolved).
    assert check(["apps/acmex/x.rs", "Package.resolved"], FakeWalls()) == ("refused", cl.REFUSED, ["Package.resolved"])


def test_any_other_file_outside_the_zone_is_still_refused_and_the_lock_is_not_listed():
    files = ["apps/acmex/x.rs", "Cargo.lock", "Cargo.toml"]
    assert check(files, FakeWalls(locks={"Cargo.lock"})) == ("refused", cl.REFUSED, ["Cargo.toml"])


def test_walls_that_cannot_be_read_refuse_the_lock_as_before():
    assert check(["apps/acmex/x.rs", "Cargo.lock"], None) == ("refused", cl.REFUSED, ["Cargo.lock"])


# Run as a script (zone-tool and Stage 2 run tests/unit's plain scripts with python3); pytest, given the file by path,
# imports it without running this and collects the test_ functions.
if __name__ == "__main__":
    failed = 0
    for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except (Exception, SystemExit) as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)
