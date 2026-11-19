#!/usr/bin/env -S python3 -u
"""Changelog notice, Stage 2 step record, checked_members, team_env and feature-save locking contracts: integration
tests, because they build a real team folder and manifest in a temp dir through cl.Team, write real
review, changelog and feature records, and take a real flock on the team's lock. The pure stopped_by tests are in
tests/unit/land-v52-tidy.py."""
import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Point the build queue at a scratch folder, so nothing these tests run reaches the checkout or the live queue.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_tidy_io", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n'
                        '[[assistants]]\nname = "Nagatha"\n[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


def cutover(team):
    (team.dir / "reviews" / "cutover.json").write_text(json.dumps({"commit": "cut", "time": "2026-11-10T12:00:00+00:00"}))


def pending(team, wo):
    (team.dir / "reviews" / f"{wo}.json").write_text(json.dumps({
        "wo": wo, "zone": "A", "feature": wo, "landed_commit": wo + "-hash", "base": "base",
        "landed_at": "same", "handed": "same", "seq": 1, "state": "pending", "by": None, "time": None, "findings": []}))


def lock_held(team):
    with (team.dir / "lock").open("a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(file, fcntl.LOCK_UN)
        return False


def review_output(has_line, after=None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        cutover(team)
        pending(team, "w1")
        ledger = root / "ledger"
        (ledger / "changelog").mkdir(parents=True)
        team.cfg["guard_ledger"] = str(ledger)
        if after:
            team.cfg["docs"] = {"enabled": True, "after": after}
        if has_line:
            (ledger / "changelog" / "w1.md").write_text("A line")
        return cl.review_entry_notice(team, "w1"), str(ledger)


def test_review_with_changelog_describes_promotion_entry():
    output, _ = review_output(True)
    assert output.endswith("your changelog line is the entry when a promotion stamps its documents"), output


def test_review_with_changelog_says_the_line_is_published_through_the_after_step():
    # Kong's line for agent-adb722e2ca7aef4de named `docs/_public`, and the stamp's
    # `make public-docs` refused it, so no promotion could stamp its documents.
    output, _ = review_output(True, after="make public-docs")
    assert output.endswith("your changelog line is the entry when a promotion stamps its documents; it is published "
                           "with them and must pass `make public-docs`"), output


def test_review_without_changelog_describes_subject_fallback():
    output, ledger = review_output(False)
    assert output.endswith(f"no changelog/w1.md in {ledger}: a promotion that stamps its documents uses the work order's first commit subject"), output


def test_review_without_guard_ledger_says_none_found():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert cl.review_entry_notice(team, "w1") == "no guard ledger found"


def test_stage2_steps_records_a_full_disk_step_as_disk_and_says_it_is_no_test_failure():
    # two Stage 2 runs died of ENOSPC and read as test failures. The exit stays 3 (SPEC v5.4
    # Stage 2 step 7); the record and the words say what stopped it.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rec = {"wo": "w1", "zone": "A", "tree": str(Path(tmp) / "no-tree")}
        results = [{"name": "unit A", "outcome": "FAIL", "seconds": 3.04, "tail": ["[Errno 28]"], "stopped_by": "disk"},
                   {"name": "unit B", "outcome": "FAIL", "seconds": 1.0, "tail": ["assert 3 == 4"]}]

        def run_steps(tree, steps, env, *, concurrent=True, on_result=None):
            for result in results:
                on_result(result)
            return False, ["FAIL unit A (3 s)", "FAIL unit B (1 s)"]

        out = io.StringIO()
        with patch.object(cl, "run_steps", side_effect=run_steps), contextlib.redirect_stdout(out):
            ok = cl.stage2_steps(team, rec, [("unit A", "a"), ("unit B", "b")], "unit")
        assert ok is False
        assert rec["stage2"] == [{"step": "unit A", "result": "disk", "seconds": 3.0, "group": "unit"},
                                 {"step": "unit B", "result": "fail", "seconds": 1.0, "group": "unit"}], rec["stage2"]
        said = out.getvalue()
        assert "DISK: unit A stopped on a full disk (No space left on device)" in said, said
        assert "not a test failure" in said and "unit B" not in said.split("DISK:", 1)[1], said
        assert "CACHE:" not in said, said


def test_stage2_steps_records_a_compile_cache_step_as_cache_and_says_it_is_no_test_failure():
    # the shared Swift compile cache stopped a step; the exit stays 3, the record and the
    # words name the cache.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rec = {"wo": "w1", "zone": "A", "tree": str(Path(tmp) / "no-tree")}
        results = [{"name": "unit A", "outcome": "FAIL", "seconds": 3.04, "tail": ["[#CompilationCaching]"],
                    "stopped_by": "cache"},
                   {"name": "unit B", "outcome": "PASS", "seconds": 1.0, "tail": ["ok"]}]

        def run_steps(tree, steps, env, *, concurrent=True, on_result=None):
            for result in results:
                on_result(result)
            return False, ["FAIL unit A (3 s)", "PASS unit B (1 s)"]

        out = io.StringIO()
        with patch.object(cl, "run_steps", side_effect=run_steps), contextlib.redirect_stdout(out):
            ok = cl.stage2_steps(team, rec, [("unit A", "a"), ("unit B", "b")], "unit")
        assert ok is False
        assert rec["stage2"] == [{"step": "unit A", "result": "cache", "seconds": 3.0, "group": "unit"},
                                 {"step": "unit B", "result": "pass", "seconds": 1.0, "group": "unit"}], rec["stage2"]
        said = out.getvalue()
        assert "CACHE: unit A stopped on an error in the machine's shared Swift compile cache" in said, said
        assert "not a test failure" in said and "Orc-Codeteam" in said and "DISK:" not in said, said


def test_checked_members_puts_each_tree_back_before_it_reads_one():
    # A tree a dead land left on its set's merge is put back before the walls check reads
    # its files, or the partner's file is refused as outside the zone's walls.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        for wo in ("w1", "w2"):
            team.save_wo({"wo": wo, "zone": "A", "tree": f"/trees/{wo}", "branch": f"wo/A/{wo}"})
        calls = []
        with patch.object(cl, "put_back_set_merge", side_effect=lambda rec: calls.append(("put back", rec["wo"]))), \
                patch.object(cl, "carried_check", return_value=None), \
                patch.object(cl, "check_work_order", side_effect=lambda team, rec: calls.append(("check", rec["wo"]))
                             or ["docs/x.md"]):
            cl.checked_members(team, ["w1", "w2"])
        assert calls == [("put back", "w1"), ("put back", "w2"), ("check", "w1"), ("check", "w2")], calls


def test_team_env_unit_group_and_no_group():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        env = cl.team_env(team)
        assert env.get("GROUP") == "unit"
        assert env.get("CODETEAM_TEST_GROUP") == "unit"
        assert "GROUP" not in cl.team_env(team, group=None)


def test_team_environment_marks_landing_jobs():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert cl.team_env(team)["CODETEAM_LANDING"] == "1"


def test_landing_runs_write_no_bytecode_unless_the_team_says():
    # a test that imported vendored code left __pycache__ in land/validate for the next run.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert cl.team_env(team)["PYTHONDONTWRITEBYTECODE"] == "1"
        team.m["env"] = {"PYTHONDONTWRITEBYTECODE": ""}
        assert cl.team_env(team)["PYTHONDONTWRITEBYTECODE"] == ""


def feature(team, rounds):
    cl.save_feature(team, {"feature": "feat", "tagged": True, "done": False, "landed": [], "rounds": rounds})


def rounds():
    return [{"n": 1, "time": "2026-11-10T09:00:00+00:00", "wos": ["w"], "reviewed": {}},
            {"n": 2, "time": "2026-11-10T13:00:00+00:00", "wos": ["x"], "reviewed": {}}]


def assert_save_locked(team, invoke):
    original = cl.save_feature
    seen = []
    def save(t, fr):
        seen.append(lock_held(t))
        return original(t, fr)
    with patch.object(cl, "save_feature", side_effect=save), contextlib.redirect_stdout(io.StringIO()):
        invoke()
    assert seen and all(seen), f"feature saved without Lock: {seen}"


def test_other_owner_feature_save_holds_lock():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        feature(team, rounds())
        with patch.dict(os.environ, {"CODETEAM_SESSION": "Nagatha"}):
            assert_save_locked(team, lambda: cl.cmd_reviewed(team, SimpleNamespace(feature="feat")))


def test_tag_feature_save_holds_lock():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert_save_locked(team, lambda: cl.tag_wo(team, {"wo": "w"}, "feat", []))


def test_feature_done_save_holds_lock():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert_save_locked(team, lambda: cl.cmd_feature_done(team, SimpleNamespace(feature="feat")))


def test_features_due_locked_holds_lock_during_save():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cl.save_feature(team, {"feature": "feat", "tagged": False, "landed": [{"wo": "w", "zone": "A", "hash": "h", "time": "2026-01-01T00:00:00"}], "rounds": []})
        assert_save_locked(team, lambda: cl.features_due_locked(team))


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
