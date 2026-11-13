"""The branch sweep deletes a v5.4 work order's wo/<zone>/<wo> branch, here and on GitHub, by the landing tool's record
of it. codeteam-land deletes only the local branch when a work order lands or is retired,
and the loop's backup has already mirrored it to GitHub, so the GitHub copies piled up (228). Real git in a temp
folder: a repo, a bare origin, one worktree, and the land/wo records the landing tool writes.

Goes: a landed work order's GitHub copy at its recorded tip, at an older state of it, rebased with every commit's
patch in the recorded tip, or with integration merged in after it landed (every commit's patch on landing); a retired one's GitHub copy that its archive ref holds (the
archive ref goes to GitHub first, since the backup mirrors branches only). Stays: a copy with a commit beyond what landed, a retired one with no archive ref or
whose archive push fails, an open work order, one checked out in a worktree, and one with no record and its own commit.
A copy with no record that only an archived landing holds (refs/archive/landing*, kept before a history rewrite) goes:
landing's own history no longer reaches it.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def load():
    os.environ.pop("SSH_AUTH_SOCK", None)
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("codeteam_sweep", str(ROOT / "bin" / "codeteam"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeTeam:
    def __init__(self, repo, root):
        self.base, self.exchange, self.integration = "main", "integration", "integration"
        self.lab, self.prefix, self.product, self.target, self.backup = False, "lane/", "p", "integration", True
        self.m = {"land": {"enabled": True}}
        self.repo, self.root = repo, root


def git(repo, *a):
    return subprocess.run([*G, "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


def refs(repo, prefix):
    return set(git(repo, "for-each-ref", "--format=%(refname:short)", prefix).split())


def commit(repo, branch, name, text):
    """One commit on `branch` (checked out here) writing `name`; its sha."""
    git(repo, "checkout", "-q", branch)
    (Path(repo) / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"{branch}: {name}")
    return git(repo, "rev-parse", "HEAD")


def record(wo_dir, wo, kind, tip):
    name = f"{wo}.{kind}.json" if kind else f"{wo}.json"
    (wo_dir / name).write_text(json.dumps({"wo": wo, "branch": f"wo/A/{wo}", "tip": tip}))


def build(d):
    """The repo and origin; each case's branch is pushed to GitHub, then handled as the landing tool would."""
    origin, repo, root = d / "origin.git", d / "repo", d / "team"
    wo_dir = root / "land" / "wo"
    wo_dir.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    git(repo, "branch", "integration")
    git(repo, "branch", "landing")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main", "integration", "landing")
    for wo in ("landed", "older", "rebased", "remerged", "squashed", "beyond", "retired", "noarchive", "reject", "open",
               "busy", "norecord", "prerewrite"):
        git(repo, "branch", f"wo/A/{wo}", "main")

    def land(wo, tip):
        git(repo, "checkout", "-q", "landing")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", tip)
        record(wo_dir, wo, "landed", tip)

    # landed at its recorded tip
    t = commit(repo, "wo/A/landed", "landed.txt", "1")
    git(repo, "push", "-q", "origin", "wo/A/landed")
    land("landed", t)
    # GitHub holds an older state of the landed tip
    commit(repo, "wo/A/older", "older.txt", "1")
    git(repo, "push", "-q", "origin", "wo/A/older")
    land("older", commit(repo, "wo/A/older", "older.txt", "2"))
    # GitHub holds the copy from before a rebase; the rebased copy landed, so every patch is on landing
    commit(repo, "wo/A/rebased", "rebased.txt", "1")
    git(repo, "push", "-q", "origin", "wo/A/rebased")
    commit(repo, "main", "main.txt", "moved on")
    git(repo, "checkout", "-q", "-b", "rebased-copy", "main")
    git(repo, "cherry-pick", "wo/A/rebased")
    land("rebased", git(repo, "rev-parse", "rebased-copy"))
    git(repo, "branch", "-q", "-D", "rebased-copy")
    # landed, then integration merged in: the commits beyond the recorded tip are on landing already
    land("remerged", commit(repo, "wo/A/remerged", "remerged.txt", "1"))
    commit(repo, "main", "main.txt", "moved on again")
    git(repo, "checkout", "-q", "landing")
    git(repo, "merge", "-q", "--no-edit", "main")
    git(repo, "checkout", "-q", "wo/A/remerged")
    git(repo, "merge", "-q", "--no-edit", "main")
    git(repo, "push", "-q", "origin", "wo/A/remerged")
    # landed as a squash (as codeteam-land lands), then integration merged in: its own commits never match landing one
    # by one (`git cherry`), and every commit outside the recorded tip and landing is a clean merge
    commit(repo, "wo/A/squashed", "squashed.txt", "1")
    t = commit(repo, "wo/A/squashed", "squashed.txt", "2")
    git(repo, "checkout", "-q", "landing")
    git(repo, "merge", "-q", "--squash", t)
    git(repo, "commit", "-q", "-m", "squashed (A)")
    record(wo_dir, "squashed", "landed", t)
    commit(repo, "main", "main.txt", "moved on a third time")
    git(repo, "checkout", "-q", "landing")
    git(repo, "merge", "-q", "--no-edit", "main")
    git(repo, "checkout", "-q", "wo/A/squashed")
    git(repo, "merge", "-q", "--no-edit", "main")
    git(repo, "push", "-q", "origin", "wo/A/squashed")
    # landed, then one more commit pushed that never landed
    land("beyond", commit(repo, "wo/A/beyond", "beyond.txt", "1"))
    commit(repo, "wo/A/beyond", "beyond.txt", "2")
    git(repo, "push", "-q", "origin", "wo/A/beyond")
    # retired: wo-retire kept the tip as refs/archive/wo/<wo>
    for wo in ("retired", "noarchive", "reject"):
        t = commit(repo, f"wo/A/{wo}", f"{wo}.txt", "1")
        git(repo, "push", "-q", "origin", f"wo/A/{wo}")
        record(wo_dir, wo, "retired", t)
        if wo != "noarchive":
            git(repo, "update-ref", f"refs/archive/wo/{wo}", t)
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nif grep -q refs/archive/wo/reject; then echo refused >&2; exit 1; fi\nexit 0\n")
    hook.chmod(0o755)
    # open: still being worked on
    commit(repo, "wo/A/open", "open.txt", "1")
    git(repo, "push", "-q", "origin", "wo/A/open")
    record(wo_dir, "open", "", git(repo, "rev-parse", "wo/A/open"))
    # landed, but its tree is still checked out
    land("busy", commit(repo, "wo/A/busy", "busy.txt", "1"))
    git(repo, "push", "-q", "origin", "wo/A/busy")
    # no record, landed before landing's history was rewritten: only the archived copy of landing holds it
    t = commit(repo, "wo/A/prerewrite", "prerewrite.txt", "1")
    git(repo, "push", "-q", "origin", "wo/A/prerewrite")
    git(repo, "checkout", "-q", "-b", "old-landing", "landing")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", t)
    git(repo, "update-ref", "refs/archive/landing-before-rewrite", "old-landing")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "-q", "-D", "old-landing")
    # GitHub only, no record, a commit of its own
    commit(repo, "wo/A/norecord", "norecord.txt", "1")
    git(repo, "push", "-q", "origin", "wo/A/norecord")
    git(repo, "checkout", "-q", "main")
    # the landing tool deletes the local branch of what landed or was retired
    for wo in ("landed", "older", "rebased", "remerged", "squashed", "beyond", "retired", "noarchive", "reject",
               "norecord", "prerewrite"):
        git(repo, "branch", "-q", "-D", f"wo/A/{wo}")
    git(repo, "worktree", "add", "-q", str(d / "busy-tree"), "wo/A/busy")
    return origin, repo, root


GONE = {"wo/A/landed", "wo/A/older", "wo/A/rebased", "wo/A/remerged", "wo/A/squashed", "wo/A/retired",
        "wo/A/prerewrite"}
KEPT = {"wo/A/beyond", "wo/A/noarchive", "wo/A/reject", "wo/A/open", "wo/A/busy", "wo/A/norecord"}


def test_wo_branches_go_by_the_landing_record_and_the_rest_stay():
    ct = load()
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        origin, repo, root = build(d)
        team = {"lanes": {"A": {}}}
        before = refs(origin, "refs/heads")
        assert GONE | KEPT <= before, before

        # dry run: says what would go (the refused archive push is not tried), deletes nothing
        assert ct.sweep_landed_branches(FakeTeam(repo, root), team, dry_run=True) == len(GONE) + 1
        assert refs(origin, "refs/heads") == before
        assert not git(origin, "for-each-ref", "refs/archive")

        n = ct.sweep_landed_branches(FakeTeam(repo, root), team, dry_run=False)
        remote = refs(origin, "refs/heads")
        local = refs(repo, "refs/heads")
        assert not (GONE & remote), GONE & remote
        assert KEPT <= remote, KEPT - remote
        assert {"wo/A/open", "wo/A/busy"} <= local, local
        assert {"main", "integration", "landing"} <= remote
        # the retired work's one off-machine copy moved from a branch to its archive ref
        assert git(origin, "rev-parse", "refs/archive/wo/retired") == git(repo, "rev-parse", "refs/archive/wo/retired")
        assert git(origin, "for-each-ref", "--format=%(refname)", "refs/archive").split() == ["refs/archive/wo/retired"]
        assert n == len(GONE)

        # a second sweep finds nothing more
        assert ct.sweep_landed_branches(FakeTeam(repo, root), team, dry_run=False) == 0


if __name__ == "__main__":
    test_wo_branches_go_by_the_landing_record_and_the_rest_stay()
    print("all passed")
