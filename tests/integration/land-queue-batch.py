#!/usr/bin/env -S python3 -u
"""Queue batch against throwaway git commits; live services and test commands are stubbed."""
import contextlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_queue_batch_git", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(cl)


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


@contextlib.contextmanager
def queued_team(root, fail_b=False):
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
    for wo in ("a", "b"):
        git(repo, "checkout", "-q", "--detach", base)
        (repo / wo).write_text(wo + "\n")
        if fail_b and wo == "b":
            (repo / "b.py").write_text('raise AssertionError("broken")\n')
            git(repo, "add", "b.py")
        git(repo, "add", wo)
        git(repo, "commit", "-qm", wo)
        tips[wo] = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    manifest = root / "team.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "a"\n'
                        '[[lanes]]\nname = "B"\npath = "b"\n'
                        '[land]\nseed_index = false\n')
    team = cl.Team(manifest)
    team.notify = Mock()
    for wo, zone in (("a", "A"), ("b", "B")):
        team.save_wo({"wo": wo, "zone": zone, "tree": str(root / ("tree-" + wo)),
                      "branch": "wo/" + wo, "tip": tips[wo], "base": base, "queued": "now", "stage2": []})
        entry = {"wo": wo, "wos": [wo], "tip": tips[wo], "base": base, "zones": [zone],
                 "files": [wo, "b.py"] if fail_b and wo == "b" else [wo],
                 "review": "land", "integration": "owed", "queued": "now", "state": "waiting"}
        (team.dir / "queue" / f"{wo}.json").write_text(json.dumps(entry))
    seen = []
    def steps(team_, tree, zones, files):
        seen.append((set(zones), set(files), (tree / "a").exists(), (tree / "b").exists()))
        command = 'python3 b.py' if fail_b else 'test -f a && test -f b'
        return [("compile", "true")], [("tests batch", command)]
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(cl, "recheck_steps", side_effect=steps))
        stack.enter_context(patch.object(cl, "team_env", return_value=dict(os.environ, CODETEAM_TEST_GROUP="integration")))
        stack.enter_context(patch.object(cl, "integration_holders", return_value=[]))
        stack.enter_context(patch.object(cl, "cleanup_landing"))
        stack.enter_context(patch.object(cl, "landing_bookkeeping"))
        stack.enter_context(patch.object(cl.codeteam_tm, "exclude"))
        stack.enter_context(patch.object(cl, "stage_admit", return_value=contextlib.nullcontext()))
        yield team, base, tips, seen


def test_batch_tree_has_both_files_and_pass_lands_both_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        with queued_team(Path(tmp)) as (team, base, tips, seen):
            assert cl.advance_queue(team) is True
            assert seen == [({"A", "B"}, {"a", "b"}, True, True)]
            assert cl.entries(team) == []
            rows = [json.loads(line) for line in (team.dir / "landed.log").read_text().splitlines()]
            assert [row["wos"] for row in rows] == [["a"], ["b"]]
            assert rows[0]["range"].split("..")[0] == base
            assert rows[1]["range"].split("..")[0] == rows[0]["hash"]
            assert git(team.repo, "rev-parse", "landing") == rows[1]["hash"]
            assert git(team.repo, "show", "landing:a") == "a"
            assert git(team.repo, "show", "landing:b") == "b"
            for row in rows:
                parents = git(team.repo, "rev-list", "--parents", "-n", "1", row["hash"]).split()
                assert len(parents) == 3
                assert parents[2] == tips[row["wos"][0]]


def test_batch_lands_while_buildq_restart_pending():
    # A pending build-queue restart does not hold a batch.
    real_stage_admit = cl.stage_admit
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        restart = root / "restart"
        stages = restart / "stages"
        stages.mkdir(parents=True)
        (stages / "live.json").write_text(json.dumps({"pid": os.getpid()}))
        request = restart / "buildq.json"
        request.write_text(json.dumps({"tip": "pending"}))
        with patch.dict(os.environ, CODETEAM_QUEUE_DIR=str(root / "queue")):
            with queued_team(root) as (team, _, _, _):
                with patch.object(cl, "stage_admit", real_stage_admit):
                    assert cl.queue_batch(team, cl.entries(team), cl) is True
                assert cl.entries(team) == []
                rows = [json.loads(line) for line in (team.dir / "landed.log").read_text().splitlines()]
                assert [row["wos"] for row in rows] == [["a"], ["b"]]
                assert git(team.repo, "show", "landing:a") == "a"
                assert git(team.repo, "show", "landing:b") == "b"
                assert request.is_file()


def test_failing_entry_is_sent_back_and_other_lands():
    with tempfile.TemporaryDirectory() as tmp:
        with queued_team(Path(tmp), fail_b=True) as (team, base, _, seen):
            assert cl.advance_queue(team) is True
            assert seen == [({"A", "B"}, {"a", "b", "b.py"}, True, True)]
            assert cl.entries(team) == []
            assert git(team.repo, "show", "landing:a") == "a"
            assert subprocess.run(["git", "-C", str(team.repo), "cat-file", "-e", "landing:b"],
                                  capture_output=True).returncode != 0
            assert "queued" not in team.wo("b")
            rows = [json.loads(line) for line in (team.dir / "landed.log").read_text().splitlines()]
            assert [row["wos"] for row in rows if row.get("hash")] == [["a"]]
            assert [row["wos"] for row in rows if row.get("result") == "integration failed"] == [["b"]]
            team.notify.assert_called_once()
            assert team.notify.call_args.args[:2] == ("Coord-B", "REQUEST")
            assert "b.py:1" in team.notify.call_args.args[2]


def test_batch_tests_integration_tip_without_unrelated_landing_commit_and_lands():
    with tempfile.TemporaryDirectory() as tmp:
        with queued_team(Path(tmp)) as (team, _, _, _):
            git(team.repo, "checkout", "-q", "integration")
            (team.repo / "proven").write_text("proven\n")
            git(team.repo, "add", "proven")
            git(team.repo, "commit", "-qm", "proven integration")
            integration_tip = git(team.repo, "rev-parse", "HEAD")
            git(team.repo, "checkout", "-q", "landing")
            (team.repo / "unrelated").write_text("unrelated\n")
            git(team.repo, "add", "unrelated")
            git(team.repo, "commit", "-qm", "unrelated landing")
            landing_tip = git(team.repo, "rev-parse", "HEAD")
            git(team.repo, "checkout", "-q", "main")
            observed = []
            original_steps = cl.recheck_steps.side_effect

            def observe(team_, tree, zones, files):
                observed.append(((tree / "proven").exists(), (tree / "unrelated").exists(),
                                 subprocess.run(["git", "-C", str(tree), "merge-base", "--is-ancestor",
                                                 integration_tip, "HEAD"], capture_output=True).returncode,
                                 subprocess.run(["git", "-C", str(tree), "merge-base", "--is-ancestor",
                                                 landing_tip, "HEAD"], capture_output=True).returncode))
                return original_steps(team_, tree, zones, files)

            cl.recheck_steps.side_effect = observe
            assert cl.advance_queue(team) is True
            assert observed == [(True, False, 0, 1)]
            assert cl.entries(team) == []
            assert git(team.repo, "show", "landing:unrelated") == "unrelated"
            assert git(team.repo, "show", "landing:a") == "a"
            assert git(team.repo, "show", "landing:b") == "b"


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
