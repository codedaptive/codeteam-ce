#!/usr/bin/env -S python3 -u
"""RIT roots must be test targets containing the selector at a word start."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_rit_roots import rit_roots

W = Path(tempfile.mkdtemp(prefix="rit-roots-"))


def put(path, text):
    file = W / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)


put("kit/tests/a.rs", "fn rit_public() {}")
put("kit/Tests/b.swift", "func rit_Swift() {}")
put("web/__tests__/c.js", "rit_js")
put("crate/lib.rs", "fn rit_private() {}")
put("empty/tests/a.rs", "fn inherit_rit_foo() {}")
for directory in ("target", ".build", "node_modules", ".hidden"):
    put(f"empty/tests/{directory}/match.rs", "rit_hidden")


def test_order_and_test_segments():
    assert rit_roots(W, ["kit/Tests", "crate", "web/__tests__", "kit/tests"], "rit_") == [
        "kit/Tests", "web/__tests__", "kit/tests"]


def test_word_start_and_skipped_directories():
    assert rit_roots(W, ["empty/tests"], "rit_") == []


def test_selector_is_literal():
    put("literal/tests/a.rs", "ritXname")
    assert rit_roots(W, ["literal/tests"], "rit.name") == []


failed = 0
for name, test in list(globals().items()):
    if name.startswith("test_") and callable(test):
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
if failed:
    print(f"{failed} failed ({W} kept)")
else:
    shutil.rmtree(W)
    print("all passed")
sys.exit(bool(failed))
