#!/usr/bin/env python3
"""Test-move landings through a throwaway repository and team."""
import json
import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

LAND = Path(__file__).resolve().parents[2] / "bin" / "codeteam-land"
W = Path(tempfile.mkdtemp(prefix="land-test-move-"))
REPO, TEAM, BUILD_QUEUE = W / "repo", W / "team", W / "build-queue"
MANIFEST, GATES = W / "team.toml", W / "gate.log"
LIB = "// Library.\npub fn read() -> u32 {\n    1 // value\n}\n"
FAILS = 0


def git(tree, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid")
    return subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True, text=True, env=env).stdout


def land(*args, session=None):
    env = {k: v for k, v in os.environ.items() if k not in ("CODETEAM_SESSION", "CODETEAM_SWT")}
    env.update(HOME=str(W / "home"), CODETEAM_QUEUE_DIR=str(BUILD_QUEUE),
               GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid")
    if session:
        env["CODETEAM_SESSION"] = session
    return subprocess.run([str(LAND), str(MANIFEST), *args], capture_output=True, text=True, env=env)


def must_land(*args, session=None):
    result = land(*args, session=session)
    if result.returncode:
        raise RuntimeError(f"{args}: {result.stdout}{result.stderr}")
    return result


def record(name):
    return json.loads((TEAM / "land" / "wo" / f"{name}.json").read_text())


def entry(name):
    return next(row for p in (TEAM / "land" / "queue").glob("*.json")
                if name in (row := json.loads(p.read_text()))["wos"])


def files(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(directory).parts}


def snapshot(tree):
    return files(tree), git(tree, "ls-files", "-s"), git(tree, "diff", "--cached"), git(tree, "rev-parse", "HEAD")


def gates():
    return GATES.read_text().splitlines() if GATES.exists() else []


def cut(name, landed=False):
    """A work order's tree; landed: its README change passed Stage 2 as docs-only, so its review is pending and its
    entry owes no integration step until a test move makes it owe one."""
    tree = Path(must_land("wo-cut", "A", name).stdout.strip())
    if landed:
        (tree / "A/README.md").write_text(f"# Documentation for {name}\n")
        git(tree, "add", "-A")
        git(tree, "commit", "-qm", "docs change")
        must_land("land", name)
    return tree


def move(tree, old, new):
    destination = tree / new
    destination.parent.mkdir(parents=True, exist_ok=True)
    (tree / old).rename(destination)


def test_doc_fix_move_and_batch():
    tree = cut("docmove", landed=True)
    assert "integration" not in entry("docmove")
    old, new = "A/tests/unit/test_x.py", "A/tests/integration/test_x.py"
    move(tree, old, new)
    (tree / "A/src/lib.rs").write_text(LIB.replace("1 // value", "1 // updated value"))
    before, jobs = gates(), files(BUILD_QUEUE)
    result = land("doc-fix", "docmove", "-m", "Move misfiled test", session="Kong")
    assert result.returncode == 0, result.stdout + result.stderr
    assert gates() == before and files(BUILD_QUEUE) == jobs == {}
    row = entry("docmove")
    assert row.get("integration") == "owed" and new in row["files"] and "A" in row["zones"]
    assert {"path": new, "from": old, "to": new, "group": "integration"} in record("docmove")["moved_tests"]
    assert record("docmove")["no_build"] == "test-move: no build; the moved tests run in the integration step"
    must_land("reviewed", "docmove", session="Kong")
    result = land("queue-run", "--once")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "integration A" in gates()[len(before):], gates()


def test_doc_fix_unit_move_refused_without_changes():
    tree = cut("unitmove", landed=True)
    old, new = "A/tests/integration/test_y.py", "A/tests/unit/test_y.py"
    move(tree, old, new)
    (tree / "A/README.md").write_text("# staged\n")
    git(tree, "add", "A/README.md")
    before = snapshot(tree)
    result = land("doc-fix", "unitmove", "-m", "Move to unit", session="Kong")
    assert result.returncode != 0 and "moves tests into the unit group" in (result.stdout + result.stderr)
    assert snapshot(tree) == before


def test_stage2_move_skips_build_and_owes_integration():
    tree = cut("stage2move")
    old, new = "A/tests/unit/test_z.py", "A/tests/integration/test_z.py"
    move(tree, old, new)
    git(tree, "add", "-A")
    git(tree, "commit", "-qm", "Move test")
    before, jobs = gates(), files(BUILD_QUEUE)
    result = land("land", "stage2move")
    label = "test-move: no build; the moved tests run in the integration step"
    assert result.returncode == 0 and label in result.stdout + result.stderr, result.stdout + result.stderr
    assert record("stage2move")["no_build"] == label
    built = [row for row in record("stage2move").get("stage2") or [] if row.get("group") in ("compile", "unit")]
    assert built == [], built
    assert gates() == before and files(BUILD_QUEUE) == jobs
    row = entry("stage2move")
    assert row.get("integration") == "owed" and new in row["files"] and "A" in row["zones"]


def setup():
    REPO.mkdir()
    BUILD_QUEUE.mkdir()
    for path, text in {"A/src/lib.rs": LIB, "A/README.md": "# Documentation\n",
                       "A/tests/unit/test_x.py": "def test_x(): pass\n",
                       "A/tests/integration/test_y.py": "def test_y(): pass\n",
                       "A/tests/unit/test_z.py": "def test_z(): pass\n"}.items():
        (REPO / path).parent.mkdir(parents=True, exist_ok=True)
        (REPO / path).write_text(text)
    git(REPO, "init", "-q", "-b", "main")
    git(REPO, "add", "-A")
    git(REPO, "commit", "-qm", "init")
    git(REPO, "branch", "integration")
    git(REPO, "branch", "landing")
    MANIFEST.write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{TEAM}"
[[lanes]]
name = "A"
path = "A"
[land]
guard_ledger = "{W / 'ledger'}"
check = ""
test = "echo $CODETEAM_TEST_GROUP {{zone}} >> {GATES}"
gates = ""
seed_index = false
interface = false
codegraph = false
notify = "true"
bob_notify = "true"
''')
    must_land("install-hook")


if __name__ == "__main__":
    try:
        setup()
        for name, test in list(globals().items()):
            if name.startswith("test_") and callable(test):
                try:
                    test()
                    print(f"PASS {name}")
                except (Exception, SystemExit):
                    FAILS += 1
                    print(f"FAIL {name}")
                    traceback.print_exc()
    except Exception:
        FAILS += 1
        traceback.print_exc()
    if FAILS:
        print(f"{FAILS} failed ({W} kept for a look)")
    else:
        shutil.rmtree(W)
        print("all passed")
    raise SystemExit(bool(FAILS))
