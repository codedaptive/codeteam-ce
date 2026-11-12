#!/usr/bin/env -S python3 -u
"""v5.4 branch layout and move-over in throwaway git repositories only."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_v54_integration", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                            env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1"))
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix="land-v54-") as tmp:
        root = Path(tmp); repo = root / "repo"; repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.name", "fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
        for zone in ("A", "B", "C"):
            (repo / zone).mkdir()
            (repo / zone / "value").write_text("base\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "branch", "integration")
        git(repo, "checkout", "-q", "--detach", "integration")
        (repo / "A" / "value").write_text("landed A\n")
        (repo / "B" / "value").write_text("landed B\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "unproven landing")
        old = git(repo, "rev-parse", "HEAD")
        git(repo, "branch", "-f", "integration", old)
        git(repo, "checkout", "-q", "main")
        manifest = root / "sample.toml"
        manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\nguard = "Kong"\n'
                            '[[lanes]]\nname = "A"\npath = "A"\n[[lanes]]\nname = "B"\npath = "B"\n'
                            '[[lanes]]\nname = "C"\npath = "C"\n[land]\nseed_index = false\ninterface = false\n')
        team = cl.Team(manifest); team.notify = Mock()
        yield team, base, old


def test_wo_cut_from_integration_excludes_landing_only_commit():
    with fixture() as (team, base, old):
        git(team.repo, "branch", "landing", old)
        git(team.repo, "branch", "-f", "integration", base)
        assert getattr(team, "landing", None) == "landing"
        cl.cmd_wo_cut(team, SimpleNamespace(zone="A", wo="fresh"))
        rec = team.wo("fresh")
        assert rec["base"] == base
        assert git(rec["tree"], "rev-parse", "HEAD") == base
        assert Path(rec["tree"], "A", "value").read_text() == "base\n"
        contains = subprocess.run(["git", "merge-base", "--is-ancestor", old, "HEAD"], cwd=rec["tree"])
        assert contains.returncode == 1


def test_move_over_landing_integration_and_one_recheck():
    with fixture() as (team, base, old):
        cl.cmd_migrate_v54(team, SimpleNamespace())
        assert git(team.repo, "rev-parse", "landing") == old
        assert git(team.repo, "rev-parse", "integration") == base
        rows = cl.read_recheck(team)
        assert len(rows) == 1
        assert {key: rows[0][key] for key in ("M", "wo", "overlapping", "zones", "move")} == {
            "M": old, "wo": "v54-move", "overlapping": [], "zones": ["A", "B", "C"], "move": True}
        move = json.loads((team.dir / "v54-move.json").read_text())
        assert move["old_integration"] == old and move["base"] == base
        assert move["done"] == ["landing", "hook", "integration", "recheck", "backlog"]
        cl.cmd_migrate_v54(team, SimpleNamespace())
        assert len(cl.read_recheck(team)) == 1
        assert len(team.notify.call_args_list) == 1


def test_a4_open_work_order_reviews_only_commits_not_on_landing_and_backlog_per_zone():
    with fixture() as (team, base, old):
        cl.cmd_wo_cut(team, SimpleNamespace(zone="A", wo="already-open"))
        rec = team.wo("already-open")
        Path(rec["tree"], "A", "own").write_text("own work\n")
        git(rec["tree"], "add", "-A"); git(rec["tree"], "commit", "-qm", "own work")
        tip = git(rec["tree"], "rev-parse", "HEAD")
        cl.cmd_migrate_v54(team, SimpleNamespace())
        assert cl.review_range(team, tip, []) == [tip]
        assert cl.review_range(team, tip, [tip]) == []
        requests = [call.args for call in team.notify.call_args_list if call.args[:2] == ("Kong", "REQUEST")]
        assert len(requests) == 1
        text = requests[0][2]
        assert all(s in text for s in (f"{base}..{old} -- A", f"{base}..{old} -- B",
                                       "v54-backlog-A", "v54-backlog-B", "reviewed backlog-A", "reviewed backlog-B"))
        records = sorted(p.name for p in (team.dir / "reviews").glob("backlog-*.json"))
        assert records == ["backlog-A.json", "backlog-B.json"]
        for zone in ("A", "B"):
            row = json.loads((team.dir / "reviews" / f"backlog-{zone}.json").read_text())
            assert row["from"] == base and row["to"] == old and row["state"] == "pending" and row["requested"]


def test_hook_refuses_unmarked_and_out_of_rule_moves():
    with fixture() as (team, base, untrailed):
        git(team.repo, "branch", "landing", base)
        git(team.repo, "branch", "-f", "integration", base)
        tree = git(team.repo, "rev-parse", f"{base}^{{tree}}")
        landed = git(team.repo, "commit-tree", tree, "-p", base, "-m", "landing\n\nLanded-By: codeteam land-one")
        cl.cmd_install_hook(team, SimpleNamespace())

        def move(branch, commit, marked=False):
            env = {key: value for key, value in os.environ.items() if key != "CODETEAM_LAND_TOOL"}
            if marked:
                env["CODETEAM_LAND_TOOL"] = "1"
            return subprocess.run(["git", "update-ref", f"refs/heads/{branch}", commit], cwd=team.repo,
                                  capture_output=True, text=True, env=env)

        result = move("landing", landed)
        assert result.returncode != 0, "unmarked landing moved to an otherwise valid landing commit"
        assert git(team.repo, "rev-parse", "landing") == base
        # A valid trailer isolates the integration/base rules from the first-parent trailer rule.
        result = move("main", landed, marked=True)
        assert result.returncode != 0, "base moved to a commit not on landing"
        result = move("landing", untrailed, marked=True)
        assert result.returncode != 0, "landing accepted a first-parent commit without its trailer"
        result = move("landing", landed, marked=True)
        assert result.returncode == 0, result.stdout + result.stderr
        result = move("integration", landed, marked=True)
        assert result.returncode != 0, "integration copied landing instead of base"
        result = move("main", landed)
        assert result.returncode != 0, "unmarked base moved to a commit already on landing"
        assert git(team.repo, "rev-parse", "main") == base
        result = move("main", landed, marked=True)
        assert result.returncode == 0, result.stdout + result.stderr
        result = move("integration", landed)
        assert result.returncode != 0, "unmarked integration moved to base's commit"
        assert git(team.repo, "rev-parse", "integration") == base
        result = move("integration", landed, marked=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert [git(team.repo, "rev-parse", branch) for branch in ("landing", "main", "integration")] == [landed, landed, landed]


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
