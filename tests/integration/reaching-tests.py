#!/usr/bin/env -S python3 -u
"""Narrow repository test scripts by tracked transitive names."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_reaching_tests import reaching_tests

W = Path(tempfile.mkdtemp(prefix="reaching-tests-"))


def put(path, text):
    file = W / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)


subprocess.run(["git", "-C", str(W), "init", "-q"], check=True)
put("tests/integration/a.py", "import middle\n")
put("tests/integration/b.sh", "echo other.py\n")
put("tests/integration/unnamed.py", "print('independent')\n")
put("tests/integration/boundary.py", "data/anchor.dat xother.py other.py.bak\n")
put("tests/integration/conftest.py", "# configuration\n")
put("tests/integration/helpers/helper.py", "# helper\n")
put("lib/middle.py", "open('lib/leaf.dat')\n")
put("lib/leaf.dat", "leaf\n")
put("lib/other.py", "pass\n")
put("data/unreferenced.bin", "data\n")
put("data/anchor.dat", "anchor\n")
put("docs/guide.md", "guide\n")
subprocess.run(["git", "-C", str(W), "add", "."], check=True)


def select(*files):
    return reaching_tests(W, "tests/integration", list(files), (".md",))


def test_transitive_import_and_named_path():
    assert select("lib/leaf.dat") == ["tests/integration/a.py", "tests/integration/unnamed.py"]


def test_basename_token():
    selected = select("lib/other.py")
    assert selected == ["tests/integration/b.sh", "tests/integration/unnamed.py"]
    assert "tests/integration/boundary.py" not in selected


def test_changed_conftest_is_unknown():
    assert select("tests/integration/conftest.py") is None


def test_changed_helper_is_unknown():
    assert select("tests/integration/helpers/helper.py") is None


def test_changed_unnamed_file_is_unknown():
    assert select("data/unreferenced.bin") is None


def test_docs_are_ignored():
    assert select("docs/guide.md") == []


def test_unnamed_test_runs():
    assert select("lib/leaf.dat") == ["tests/integration/a.py", "tests/integration/unnamed.py"]


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
