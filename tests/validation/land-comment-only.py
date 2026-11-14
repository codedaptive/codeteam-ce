#!/usr/bin/env -S python3 -u
"""codeteam-land, comment-only work orders: a work order whose code files differ
from its base only in comments lands with no build and no tests, says so in its record, and triggers no recheck; a
comment change inside a Rust doc test lands normally. A throwaway repo with one zone, A, whose test step writes to
gate.log, as tests/validation/land-docs.py does."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-comment-only-"))
REPO, ROOT = W / "repo", W / "team"
fails = 0


def sh(cmd, cwd=REPO, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def land(*args):
    e = {k: v for k, v in os.environ.items() if k != "CODETEAM_SESSION"}
    e["HOME"] = str(W / "home")
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@t")):
        e.setdefault(k, v)
    result = subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)
    if args[0] == "land" and result.returncode == 0:
        row = json.loads((ROOT / "land" / "reviews" / f"{args[1]}.json").read_text())
        for reviewer in row["reviewers"]:
            verdict = subprocess.run([LAND, str(W / "team.toml"), "reviewed", args[1]], capture_output=True, text=True,
                                     env=dict(e, CODETEAM_SESSION=reviewer))
            assert verdict.returncode == 0, verdict.stdout + verdict.stderr
    return result


def cut(name, edits):
    tree = Path(land("wo-cut", "A", name).stdout.strip())
    for path, text in edits.items():
        (tree / path).write_text(text)
    sh(f"git add -A && git -c user.email=t@t -c user.name=l commit -q -m {name}", cwd=tree)
    return tree


gates = lambda: (W / "gate.log").read_text().count("A") if (W / "gate.log").exists() else 0
landed = lambda: [json.loads(line) for line in (ROOT / "land" / "landed.log").read_text().splitlines() if line.strip()] \
    if (ROOT / "land" / "landed.log").exists() else []

LIB = "// The library.\npub fn read() -> u32 {\n    1 // one\n}\n"
DOC = "/// Writes.\n///\n/// ```\n/// write(); // one\n/// ```\npub fn write() {}\n"
REPO.mkdir()
for path, text in {"A/src/lib.rs": LIB, "A/src/doc.rs": DOC, "A/Cargo.toml": '[package]\nname = "a" # crate\n'}.items():
    (REPO / path).parent.mkdir(parents=True, exist_ok=True)
    (REPO / path).write_text(text)
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git branch integration && git branch landing")
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
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
land("install-hook")

print("== a comment-only work order: no build, no tests, labelled, no recheck")
cut("comments", {"A/src/lib.rs": LIB.replace("// one", "// the only value").replace("The library.", "The library, read-only."),
                 "A/Cargo.toml": '# Package.\n[package]\nname = "a" # the crate\n'})
code_tree = cut("doctest", {"A/src/doc.rs": DOC.replace("// one", "// two")})
n0 = gates()
r = land("land", "comments")
t("it passes Stage 2 and says so", r.returncode == 0 and "Stage 2 passed (comment-only: no build, no tests)" in r.stdout,
  r.stdout + r.stderr)
t("it runs no build and no tests", gates() == n0, (n0, gates()))
rec = json.loads((ROOT / "land" / "wo" / "comments.json").read_text())
t("its record says comment-only: no build, no tests", rec.get("no_build") == "comment-only: no build, no tests", rec)
q = land("queue-run", "--once")
row = next((x for x in landed() if x["wos"] == ["comments"]), {})
t("it lands, and the landing row says comment-only: no build, no tests",
  row.get("no_build") == "comment-only: no build, no tests" and not row.get("recheck"), (row, q.stdout + q.stderr))
t("the landed line says so too", "(comment-only: no build, no tests)" in q.stdout, q.stdout)

print("== a comment change inside a Rust doc test lands normally")
r = land("land", "doctest")
t("it passes Stage 2 without the label", r.returncode == 0 and "comment-only" not in r.stdout, r.stdout + r.stderr)
t("it runs its zone's tests", gates() > n0, (n0, gates()))
rec = json.loads((ROOT / "land" / "wo" / "doctest.json").read_text())
t("its record has no no-build label", "no_build" not in rec, rec)
q = land("queue-run", "--once")
row = next((x for x in landed() if x["wos"] == ["doctest"]), {})
t("it lands", bool(row), q.stdout + q.stderr)
t("the comment-only landing before it triggers no recheck", not row.get("recheck"), row)

if fails:
    print(f"\n{fails} FAILED  ({W} kept for a look)")
else:
    shutil.rmtree(W, ignore_errors=True)     # its own throwaway folder
    print("\nall passed")
raise SystemExit(1 if fails else 0)
