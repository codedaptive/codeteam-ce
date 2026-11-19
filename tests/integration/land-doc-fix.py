#!/usr/bin/env python3
"""Stage 3 doc-fix through the landing CLI in an isolated repo and team (D574)."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

LAND = Path(__file__).resolve().parents[2] / "bin" / "codeteam-land"
W = Path(tempfile.mkdtemp(prefix="land-doc-fix-"))
REPO, ROOT, BUILD_QUEUE = W / "repo", W / "team", W / "build-queue"
MANIFEST = W / "team.toml"
LIB = "// Library.\npub fn read() -> u32 {\n    1 // value\n}\n"
TOOL = '"""Original documentation."""\ndef run():\n    return 1\n'
FAILS = 0


def check(label, condition, detail=""):
    global FAILS
    print(("  PASS " if condition else "  FAIL ") + label + ("" if condition else f"  [{detail}]"), flush=True)
    FAILS += not condition


def git(tree, *args):
    result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True,
                            env=dict(os.environ, GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
                                     GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid"))
    if result.returncode:
        raise RuntimeError(f"git {args}: {result.stdout}{result.stderr}")
    return result.stdout


def land(*args, session=None):
    env = {k: v for k, v in os.environ.items() if k not in ("CODETEAM_SESSION", "CODETEAM_SWT")}
    env.update(HOME=str(W / "home"), CODETEAM_QUEUE_DIR=str(BUILD_QUEUE),
               GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid")
    if session is not None:
        env["CODETEAM_SESSION"] = session
    return subprocess.run([str(LAND), str(MANIFEST), *args], capture_output=True, text=True, env=env)


def must_land(*args, session=None):
    result = land(*args, session=session)
    if result.returncode:
        raise RuntimeError(f"{args}: {result.stdout}{result.stderr}")
    return result


def record(name):
    return json.loads((ROOT / "land" / "wo" / f"{name}.json").read_text())


def review(name):
    return json.loads((ROOT / "land" / "reviews" / f"{name}.json").read_text())


def queued(name):
    return next(p for p in (ROOT / "land" / "queue").glob("*.json")
                if name in json.loads(p.read_text())["wos"])


def files_under(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(directory).parts}


def snapshot(tree):
    return (files_under(tree), git(tree, "ls-files", "-s"),
            git(tree, "diff", "--cached", "--name-only"), git(tree, "rev-parse", "HEAD"))


def gate_lines():
    path = W / "gate.log"
    return path.read_text().splitlines() if path.exists() else []


def cut_and_queue(name):
    tree = Path(must_land("wo-cut", "A", name).stdout.strip())
    (tree / "A/src/lib.rs").write_text(LIB.replace("    1 //", "    2 //"))
    git(tree, "add", "-A")
    git(tree, "commit", "-qm", f"code change {name}")
    before = len(gate_lines())
    must_land("land", name)
    rec, row = record(name), review(name)
    if (len(gate_lines()) <= before or not rec.get("stage2") or row.get("state") != "pending"
            or row.get("reviewers") != {"Kong": "pending"}):
        raise RuntimeError(f"{name}: Stage 2 or pending Kong review missing: {rec}, {row}")
    return Path(rec["tree"])


def success_case():
    name = "docs"
    tree = cut_and_queue(name)
    (tree / "A/src/lib.rs").write_text(LIB.replace("    1 // value", "    2 // updated value"))
    (tree / "A/README.md").write_text("# Updated documentation\n")
    (tree / "A/new.md").write_text("# New documentation\n")
    rec0, row0 = record(name), review(name)
    entry_path = queued(name)
    entry0 = json.loads(entry_path.read_text())
    old = git(tree, "rev-parse", "HEAD").strip()
    gates0, jobs0 = gate_lines(), files_under(BUILD_QUEUE)
    result = land("doc-fix", name, "-m", "Correct documentation", session="Kong")
    output = result.stdout + result.stderr
    check("doc-fix accepts comments and existing and new Markdown", result.returncode == 0, output)
    check("doc-fix runs no test step", gate_lines() == gates0, (gates0, gate_lines()))
    check("doc-fix adds no build-queue job", files_under(BUILD_QUEUE) == jobs0 == {},
          (jobs0, files_under(BUILD_QUEUE)))
    if result.returncode:
        return
    new = git(tree, "rev-parse", "HEAD").strip()
    check("new commit has the old tip as its only parent", new != old and git(tree, "rev-list", "--parents", "-n", "1", new).split() == [new, old])
    check("commit has exactly the requested message and trailers",
          git(tree, "show", "-s", "--format=%B", new).rstrip("\n") ==
          "Correct documentation\n\nMade-By: codeteam-land doc-fix\nDoc-fix-by: Kong")
    rec1, row1 = record(name), review(name)
    entry1 = json.loads(queued(name).read_text())
    check("record moves tip, records doc-fix and adds the new file",
          rec1.get("tip") == new and rec1.get("doc_fixes") == [new]
          and set(rec1["files"]) == set(rec0["files"]) | {"A/README.md", "A/new.md"}, rec1)
    check("Stage 2, zones, reach and other record fields stand",
          {k: v for k, v in rec1.items() if k not in ("tip", "files", "doc_fixes")} ==
          {k: v for k, v in rec0.items() if k not in ("tip", "files", "doc_fixes")})
    check("queue keeps its place, zones and owed integration with the new tip",
          entry0.get("integration") == "owed" and queued(name) == entry_path
          and entry1 == dict(entry0, tip=new), (entry0, entry1))
    check("review moves to new tip and remains pending for Kong",
          row1 == dict(row0, tip=new) and row1["reviewers"] == {"Kong": "pending"}, row1)
    check("output gives the exact show and reviewed commands",
          f"git -C {tree} show {new}" in output and f"codeteam-land {MANIFEST} reviewed {name}" in output, output)
    verdict = land("reviewed", name, session="Kong")
    check("Kong can approve the new tip", verdict.returncode == 0, verdict.stdout + verdict.stderr)
    run = land("queue-run", "--once")
    landed_ref = subprocess.run(["git", "-C", str(REPO), "rev-parse", f"refs/landed/{name}"],
                                capture_output=True, text=True)
    check("queue-run lands the new tip", run.returncode == 0 and landed_ref.returncode == 0
          and landed_ref.stdout.strip() == new, run.stdout + run.stderr + landed_ref.stderr)


def refusal_case(name, path, content):
    tree = cut_and_queue(name)
    # Keep a staged change as well as the code edit, to test the real index on refusal.
    (tree / "A/README.md").write_text("# Staged documentation\n")
    git(tree, "add", "A/README.md")
    (tree / path).write_text(content)
    before = snapshot(tree)
    result = land("doc-fix", name, "-m", "Try code", session="Kong")
    output = result.stdout + result.stderr
    check(f"{name}: code is refused and its path named", result.returncode != 0
          and "code" in output.lower() and path in output, output)
    check(f"{name}: files, real index and HEAD stay unchanged", snapshot(tree) == before)


def git_facts_refusal_case(name, wording, state):
    tree = cut_and_queue(name)
    branch = f"refs/heads/{record(name)['branch']}"
    if state == "ahead":
        (tree / "A/README.md").write_text("# Committed after review\n")
        git(tree, "add", "A/README.md")
        git(tree, "commit", "-qm", "Commit after review")
    elif state == "detached":
        git(tree, "checkout", "--detach")
    (tree / "A/README.md").write_text("# Staged documentation\n")
    git(tree, "add", "A/README.md")
    if state == "outside":
        (tree / "B/x.md").write_text("# Outside the zone\n")
    else:
        (tree / "A/README.md").write_text("# Unstaged documentation\n")
    before = snapshot(tree), git(tree, "rev-parse", branch)
    result = land("doc-fix", name, "-m", "Fix documentation", session="Kong")
    output = result.stdout + result.stderr
    check(f"{name}: refusal explains {wording}", result.returncode != 0
          and wording in output and (state != "outside" or "B/x.md" in output), output)
    check(f"{name}: files, real index, HEAD and branch stay unchanged",
          (snapshot(tree), git(tree, "rev-parse", branch)) == before)


def stale_entry_case():
    name = "stale-entry"
    tree = cut_and_queue(name)
    entry_path = queued(name)
    entry = json.loads(entry_path.read_text())
    entry_path.write_text(json.dumps(dict(entry, tip="0" * 40), indent=1) + "\n")
    (tree / "A/README.md").write_text("# Documentation fix\n")
    branch = f"refs/heads/{record(name)['branch']}"
    before = snapshot(tree), git(tree, "rev-parse", branch)
    result = land("doc-fix", name, "-m", "Fix documentation", session="Kong")
    output = result.stdout + result.stderr
    check(f"{name}: a queue entry not at the tip is refused", result.returncode != 0, output)
    check(f"{name}: files, real index, HEAD and branch stay unchanged",
          (snapshot(tree), git(tree, "rev-parse", branch)) == before)


def reviewer_case(name, session, approve_first=False):
    tree = cut_and_queue(name)
    if approve_first:
        must_land("reviewed", name, session="Kong")
        if review(name).get("state") == "pending":
            raise RuntimeError(f"{name}: review is still pending")
    (tree / "A/README.md").write_text("# Reviewer edit\n")
    before = snapshot(tree)
    result = land("doc-fix", name, "-m", "Reviewer edit", session=session)
    output = result.stdout + result.stderr
    reason = "no pending" if approve_first else "Coord-A"
    check(f"{name}: reviewer restriction is explained", result.returncode != 0
          and reason.lower() in output.lower() and "review" in output.lower(), output)
    check(f"{name}: files, real index and HEAD stay unchanged", snapshot(tree) == before)


def setup():
    REPO.mkdir()
    BUILD_QUEUE.mkdir()
    for path, text in {"A/src/lib.rs": LIB, "A/tool.py": TOOL, "A/README.md": "# Documentation\n",
                       "A/Cargo.toml": '[package]\nname = "a"\nversion = "0.1.0"\n',
                       "B/README.md": "# Lane B\n"}.items():
        (REPO / path).parent.mkdir(parents=True, exist_ok=True)
        (REPO / path).write_text(text)
    git(REPO, "init", "-q", "-b", "main")
    git(REPO, "add", "-A")
    git(REPO, "commit", "-qm", "init")
    git(REPO, "branch", "integration")
    git(REPO, "branch", "landing")
    MANIFEST.write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
[[lanes]]
name = "B"
path = "B"
[land]
guard_ledger = "{W / 'ledger'}"
check = ""
test = "echo {{zone}} >> {W / 'gate.log'}"
gates = ""
seed_index = false
interface = false
codegraph = false
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
bob_notify = "true"
''')
    must_land("install-hook")


def main():
    setup()
    cases = [
        ("success and landing", success_case),
        ("Rust code", lambda: refusal_case("rust-code", "A/src/lib.rs", LIB.replace("    1 //", "    3 //"))),
        ("Python docstring", lambda: refusal_case("docstring", "A/tool.py", TOOL.replace("Original", "Changed"))),
        ("new code", lambda: refusal_case("new-code", "A/src/new.rs", "pub fn new() {}\n")),
        ("HEAD past the reviewed tip", lambda: git_facts_refusal_case("head-ahead", "not its reviewed tip", "ahead")),
        ("tree detached", lambda: git_facts_refusal_case("tree-detached", "not on its branch", "detached")),
        ("outside the zone", lambda: git_facts_refusal_case("outside-zone", "outside its zone", "outside")),
        ("queue entry not at the tip", stale_entry_case),
        ("wrong reviewer", lambda: reviewer_case("wrong-reviewer", "Coord-A")),
        ("no pending review", lambda: reviewer_case("no-review", "Kong", approve_first=True)),
    ]
    for label, case in cases:
        print(f"== {label}", flush=True)
        try:
            case()
        except (RuntimeError, OSError, KeyError, StopIteration) as exc:
            check(f"{label}: setup or record access", False, exc)


try:
    main()
except (RuntimeError, OSError) as exc:
    check("setup", False, exc)
if FAILS:
    print(f"\n{FAILS} FAILED  ({W} kept for a look)")
else:
    shutil.rmtree(W)
    print("\nall passed")
raise SystemExit(1 if FAILS else 0)
