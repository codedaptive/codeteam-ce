#!/usr/bin/env -S python3 -u
"""What a changed file in no zone's scope reaches: unscoped_reach in a throwaway Git workspace."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_unscoped_reach import unscoped_reach  # noqa: E402

DOCS = (".md",)
W = Path(tempfile.mkdtemp(prefix="unscoped-reach-"))
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def git(*args):
    return subprocess.run(["git", "-C", str(W), *args], check=True, text=True, capture_output=True).stdout.strip()


def commit(message):
    git("add", "-A")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", message)
    return git("rev-parse", "HEAD")


def lock(a_deps, c_deps):
    entry = '[[package]]\nname = "{}"\nversion = "1.0.0"\ndependencies = [{}]\n'
    return "version = 3\n\n" + "\n".join(entry.format(n, ", ".join(f'"{d}"' for d in deps))
                                         for n, deps in (("a", a_deps), ("b", ["a"]), ("c", c_deps), ("d", [])))


def owners(folder):
    """Zone za holds crates/a, zb crates/b; no zone holds crates/c."""
    return {"crates/a": {"za"}, "crates/b": {"zb"}}.get(folder, set())


git("init", "-q")
(W / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n')
for name in "abcd":
    (W / "crates" / name).mkdir(parents=True)
    (W / "crates" / name / "Cargo.toml").write_text(f'[package]\nname = "{name}"\nversion = "1.0.0"\n')
(W / "Cargo.lock").write_text(lock([], []))
first = commit("workspace")
(W / "Cargo.lock").write_text(lock(["d"], []))
second = commit("a gains d")
(W / "Cargo.lock").write_text(lock(["d"], ["d"]))
commit("c gains d")

r = unscoped_reach(W, "docs/lanes/tools.md", first, DOCS, owners)
t("a document reaches nothing", r == set(), r)
r = unscoped_reach(W, "Makefile", first, DOCS, owners)
t("any other file reaches no kit: contracts name its consumers", r == set(), r)
r = unscoped_reach(W, "Cargo.lock", None, DOCS, owners)
t("a Cargo.lock with no base is unknown", r is None, r)
git("checkout", "-q", second)
r = unscoped_reach(W, "Cargo.lock", first, DOCS, owners)
t("a lock change reaches the zone holding the crate it changes", r == {"za"}, r)
git("checkout", "-q", "-")
r = unscoped_reach(W, "Cargo.lock", second, DOCS, owners)
t("a lock change to a folder no zone holds is unknown", r is None, r)
if fails:
    print(f"\n{fails} failed  ({W} kept for a look)")
else:
    shutil.rmtree(W, ignore_errors=True)
    print("\nall passed")
sys.exit(1 if fails else 0)
