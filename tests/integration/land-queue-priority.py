#!/usr/bin/env -S python3 -u
"""Queue priority against throwaway git commits; live services are stubbed."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_queue_priority_git", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(cl)


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


@contextlib.contextmanager
def queued_team(root, owed=True, urgent_severity=2):
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "base").write_text("base\n")
    git(repo, "add", "base")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "branch", "landing", base)
    git(repo, "branch", "integration", base)
    tips = {}
    for wo in ("minor", "new", "urgent"):
        git(repo, "checkout", "-q", "--detach", base)
        (repo / wo).write_text(wo + "\n")
        git(repo, "add", wo)
        git(repo, "commit", "-qm", wo)
        tips[wo] = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    manifest = root / "team.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "."\n'
                        '[land]\nseed_index = false\n')
    team = cl.Team(manifest)
    team.notify = Mock()
    for number, wo in enumerate(("minor", "new", "urgent"), 1):
        fixes = {"minor": ["f3"], "new": [], "urgent": ["f2"]}[wo]
        team.save_wo({"wo": wo, "zone": "A", "tree": str(root / ("tree-" + wo)),
                      "branch": "wo/" + wo, "tip": tips[wo], "base": base, "queued": "now",
                      "stage2": [], "fixes": fixes})
        entry = {"wo": wo, "wos": [wo], "tip": tips[wo], "base": base, "zones": ["A"],
                 "files": [wo], "review": "land", "queued": "now", "state": "waiting"}
        if owed:
            entry["integration"] = "owed"
        (team.dir / "queue" / f"{number}-{wo}.json").write_text(json.dumps(entry))
    (team.dir / "findings").mkdir()
    (team.dir / "findings" / "feature.json").write_text(json.dumps([
        {"id": "f3", "severity": 3}, {"id": "f2", "severity": urgent_severity},
    ]))
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(cl, "recheck_steps", return_value=([("compile", "true")], [("tests", "true")])))
        stack.enter_context(patch.object(cl, "team_env", return_value=dict(os.environ, CODETEAM_TEST_GROUP="integration")))
        stack.enter_context(patch.object(cl, "integration_holders", return_value=[]))
        stack.enter_context(patch.object(cl, "cleanup_landing"))
        stack.enter_context(patch.object(cl, "landing_bookkeeping"))
        stack.enter_context(patch.object(cl.codeteam_tm, "exclude"))
        stack.enter_context(patch.object(cl, "stage_admit", return_value=contextlib.nullcontext()))
        yield team


def landed(team):
    return [json.loads(line)["wos"] for line in (team.dir / "landed.log").read_text().splitlines()]


def queue_lines(team):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        cl.cmd_queue(team, SimpleNamespace())
    return output.getvalue().splitlines()


def test_owed_batch_lands_in_priority_order():
    with tempfile.TemporaryDirectory() as tmp, queued_team(Path(tmp)) as team:
        assert cl.advance_queue(team) is True
        assert landed(team) == [["urgent"], ["new"], ["minor"]]
        assert cl.entries(team) == []


def test_unowed_entries_land_one_per_call_in_priority_order():
    with tempfile.TemporaryDirectory() as tmp, queued_team(Path(tmp), owed=False) as team:
        for expected in (["urgent"], ["urgent", "new"], ["urgent", "new", "minor"]):
            assert cl.advance_queue(team) is True
            assert [row[0] for row in landed(team)] == expected


def test_queue_lists_take_order_and_priority():
    with tempfile.TemporaryDirectory() as tmp, queued_team(Path(tmp)) as team:
        lines = queue_lines(team)
        assert len(lines) == 3
        assert "urgent" in lines[0] and "prio 0" in lines[0]
        assert "new" in lines[1] and "prio 1" in lines[1]
        assert "minor" in lines[2] and "prio 2" in lines[2]


def test_land_next_overrides_priority_for_listing_and_landing():
    with tempfile.TemporaryDirectory() as tmp, queued_team(Path(tmp), owed=False) as team:
        cl.cmd_land_next(team, SimpleNamespace(wo="minor"))
        lines = queue_lines(team)
        assert "minor" in lines[0] and "prio next" in lines[0]
        assert cl.advance_queue(team) is True
        assert landed(team) == [["minor"]]


def test_unowed_new_work_lands_before_owed_urgent_fix():
    with tempfile.TemporaryDirectory() as tmp, queued_team(Path(tmp), urgent_severity=1) as team:
        path = team.dir / "queue" / "2-new.json"
        entry = json.loads(path.read_text())
        del entry["integration"]
        path.write_text(json.dumps(entry))
        assert cl.advance_queue(team) is True
        assert landed(team) == [["new"]]


def test_queue_priorities_reads_findings_once():
    with tempfile.TemporaryDirectory() as tmp, queued_team(Path(tmp)) as team:
        queued = {p: json.loads(p.read_text()) for p in cl.entries(team)}
        with patch.object(cl, "all_findings", wraps=cl.all_findings) as findings:
            priorities = cl.queue_priorities(team, queued)
        assert [priorities[p] for p in queued] == [2, 1, 0]
        assert findings.call_count == 1


def test_queue_priorities_skips_unreadable_and_non_dict_records():
    with tempfile.TemporaryDirectory() as tmp, queued_team(Path(tmp)) as team:
        (team.dir / "wo" / "broken.json").write_text("{")
        (team.dir / "wo" / "list.json").write_text("[]")
        paths = [team.dir / "queue" / f"test-{n}.json" for n in range(4)]
        queued = {paths[0]: {"wos": ["broken"]}, paths[1]: {"wos": ["list"]},
                  paths[2]: {"wos": ["missing"]}, paths[3]: {"wos": ["broken", "urgent"]}}
        priorities = cl.queue_priorities(team, queued)
        assert [priorities[p] for p in paths] == [1, 1, 1, 0]


if __name__ == "__main__":
    failures = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"PASS {name}")
            except (Exception, SystemExit):
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"{failures} failed")
    sys.exit(bool(failures))
