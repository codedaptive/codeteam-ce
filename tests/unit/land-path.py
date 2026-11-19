#!/usr/bin/env -S python3 -u
"""The landing tool constructs its PATH at import, isolated from this runner."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def imported_path(home, inherited):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CODETEAM_QUEUE_DIR"] = str(home / "queue")
    if inherited is None:
        env.pop("PATH", None)
    else:
        env["PATH"] = inherited
    child = """
import importlib.machinery
import importlib.util
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader("cl_path", sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
with patch("subprocess.run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(module)
print(os.environ["PATH"])
"""
    result = subprocess.run([sys.executable, "-c", child, str(ROOT / "bin" / "codeteam-land")],
                            env=env, capture_output=True, text=True, check=True)
    return result.stdout.strip().split(":")


def test_import_path_preserves_inherited_order():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        got = imported_path(home, "/x/bin:/usr/bin")
        want = [str(ROOT / "bin"), str(ROOT / "v2" / "bin"), str(home / ".cargo" / "bin"),
                "/opt/homebrew/bin", "/x/bin", "/usr/bin", "/bin"]
        assert got == want, f"got {got!r}, expected {want!r}"


def test_import_path_deduplicates_preferred_entries():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        got = imported_path(home, f"/opt/homebrew/bin:{ROOT / 'bin'}:/y")
        want = [str(ROOT / "bin"), str(ROOT / "v2" / "bin"), str(home / ".cargo" / "bin"),
                "/opt/homebrew/bin", "/y", "/usr/bin", "/bin"]
        assert got == want, f"got {got!r}, expected {want!r}"


def test_import_path_defaults_when_unset():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        got = imported_path(home, None)
        want = [str(ROOT / "bin"), str(ROOT / "v2" / "bin"), str(home / ".cargo" / "bin"),
                "/opt/homebrew/bin", "/usr/bin", "/bin"]
        assert got == want, f"got {got!r}, expected {want!r}"


failed = 0
for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)
             and (len(sys.argv) == 1 or k in sys.argv[1:])]:
    try:
        test()
        print(f"  PASS {test.__name__}")
    except (Exception, SystemExit) as exc:
        failed += 1
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
