#!/usr/bin/env -S python3 -u
"""Isolated changelog notices, locking and build queue restart contracts."""
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

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_tidy", str(ROOT / "bin" / "codeteam-land"))
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


def rec(wo):
    return {"wo": wo, "zone": "A", "landed_commit": wo + "-hash", "landed_base": "base", "landed_at": "same"}


def pending(team, wo):
    (team.dir / "reviews" / f"{wo}.json").write_text(json.dumps({
        "wo": wo, "zone": "A", "feature": wo, "landed_commit": wo + "-hash", "base": "base",
        "landed_at": "same", "handed": "same", "seq": 1, "state": "pending", "by": None, "time": None, "findings": []}))


def marker(qdir):
    p = qdir.parent / "restart" / "buildq.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"requested": "now", "requested_ts": 1, "tip": "0123456789abcdef", "files": [], "waited": []}))
    return p


def job(qdir, ticket, state, landing, key="unit A"):
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / f"{ticket}.json").write_text(json.dumps({"ticket": ticket, "key": key, "state": state,
                                                       "env": {"CODETEAM_LANDING": landing}}))


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
    # 2026-11-12: Kong's line for a work order named `docs/_public`, and the stamp's
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


def test_stage_admission_creates_and_removes_record():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        with cl.stage_admit("Stage 2", "check of a", qdir=qdir):
            files = list((qdir.parent / "restart" / "stages").glob("*.json"))
            assert len(files) == 1
            row = json.loads(files[0].read_text())
            assert row["stage"] == "Stage 2" and row["name"] == "check of a" and row["pid"] == os.getpid() and row["started"]
        assert not files[0].exists()


def holder_row(stages, pid, team_key, wos, name="hold"):
    stages.mkdir(parents=True, exist_ok=True)
    (stages / f"{name}.json").write_text(json.dumps({"stage": "Stage 2", "name": f"check of {', '.join(wos)}",
                                                     "pid": pid, "started": "06:10", "team": team_key, "wos": wos}))


def test_stage_admission_refuses_a_work_order_a_live_land_of_the_team_holds():
    # A second land of w2, the --with member of a live land mid Stage 2, read the set's merge
    # in the tree and was refused for the other member's files; it is refused by name, before any record is read.
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        stages = qdir.parent / "restart" / "stages"
        holder_row(stages, os.getppid(), "/t.toml", ["w1", "w2"])
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), cl.stage_admit("Stage 2", "check of w2", qdir=qdir,
                                                                  holds=("/t.toml", ["w2"])):
                raise AssertionError("admitted while a live land holds w2")
        except SystemExit as exc:
            assert exc.code == cl.REFUSED
        assert err.getvalue().startswith(f"w2: a land of it is already running (pid {os.getppid()}, Stage 2 check of "
                                         "w1, w2, since 06:10)"), err.getvalue()
        assert f"kill -TERM {os.getppid()}" in err.getvalue()
        assert [p.name for p in stages.glob("*.json")] == ["hold.json"]


def test_stage_admission_admits_beside_another_teams_land_or_other_work_orders_and_records_its_own():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        stages = qdir.parent / "restart" / "stages"
        holder_row(stages, os.getppid(), "/other.toml", ["w2"], "other-team")
        holder_row(stages, os.getppid(), "/t.toml", ["w9"], "other-wo")
        with cl.stage_admit("Stage 2", "check of w2", qdir=qdir, holds=("/t.toml", ["w2"])):
            mine = [json.loads(p.read_text()) for p in stages.glob("*.json") if p.stem.startswith(f"{os.getpid()}-")]
            assert [(r["team"], r["wos"]) for r in mine] == [("/t.toml", ["w2"])]


def test_stage_holders_skips_a_dead_holder_and_its_own_process():
    with tempfile.TemporaryDirectory() as tmp:
        rdir = Path(tmp) / "restart"
        holder_row(rdir / "stages", 10, "/t.toml", ["w1"], "dead")
        holder_row(rdir / "stages", os.getpid(), "/t.toml", ["w1"], "own")
        holder_row(rdir / "stages", 12, "/t.toml", ["w1"], "live")
        assert [r["pid"] for r in cl.stage_holders(rdir, "/t.toml", ["w1"], alive=lambda pid: pid != 10)] == [12]


def test_stage_holders_reads_a_land_recorded_before_d394_by_its_name():
    # A land started by an older landing tool recorded no team or wos, only "check of a, b". The next land puts a set merge
    # back on its branch, so such a land, still running, must hold its work orders too. A Stage 5 record holds none.
    with tempfile.TemporaryDirectory() as tmp:
        rdir = Path(tmp) / "restart"
        (rdir / "stages").mkdir(parents=True)
        (rdir / "stages" / "old.json").write_text(json.dumps({"stage": "Stage 2", "name": "check of w1, w2", "pid": 12,
                                                              "started": "05:48"}))
        (rdir / "stages" / "recheck.json").write_text(json.dumps({"stage": "Stage 5", "name": "recheck of w2 at M 1",
                                                                  "pid": 13, "started": "05:50"}))
        assert [r["pid"] for r in cl.stage_holders(rdir, "/t.toml", ["w2"], alive=lambda pid: True)] == [12]
        assert cl.stage_holders(rdir, "/t.toml", ["w3"], alive=lambda pid: True) == []


def test_stopped_by_reads_each_tools_full_disk_error_on_a_step_that_did_not_pass():
    # Python, Rust (cargo, rustc), git and the shell each say ENOSPC their own way.
    for said in ("OSError: [Errno 28] No space left on device: '/team-acme/land/tmp/x'",
                 "error: failed to write `target/debug/deps/x.rmeta`: No space left on device (os error 28)",
                 "fatal: write error: No space left on device",
                 "sh: line 1: echo: write error: ENOSPC"):
        assert cl.stopped_by("FAIL", said) == "disk", said
        assert cl.stopped_by("HUNG", said) == "disk", said
    assert cl.stopped_by("PASS", "test_enospc_is_reported ... No space left on device ... ok") is None
    assert cl.stopped_by("FAIL", "assertion failed: left == right (3 != 4)") is None


def test_stopped_by_reads_the_swift_compile_cache_error_on_a_step_that_did_not_pass():
    # Xcode's shared compile cache once failed a package's check with this line;
    # the cache, not the work order. A full disk named in the same output is the cause, so it reads as "disk".
    said = ("<unknown>:0: error: cannot create CAS filesystem: not a IncludeFileList node kind "
            "[#CompilationCaching]")
    assert cl.stopped_by("FAIL", said) == "cache"
    assert cl.stopped_by("HUNG", said) == "cache"
    assert cl.stopped_by("PASS", said) is None
    assert cl.stopped_by("FAIL", said + "\nerror: No space left on device") == "disk"
    assert cl.stopped_by("FAIL", "note: see [#CompilationCaching] for how the cache works") is None
    # A stored result that cannot be read back, then cannot be replaced; neither line is tagged.
    for said in ("error: CAS error: unsupported compile result schema found",
                 "error: failed to update cache: cache poisoned for 'e37ee2e9c191648a' (new='llvmcas://05026ffa' vs. "
                 "existing 'llvmcas://85fa99d3')"):
        assert cl.stopped_by("FAIL", said) == "cache", said
        assert cl.stopped_by("PASS", said) is None, said
    assert cl.stopped_by("FAIL", "XCTAssertEqual failed: the cache poisoned flag was not set") is None


def test_stage2_steps_records_a_full_disk_step_as_disk_and_says_it_is_no_test_failure():
    # Two Stage 2 runs once died of ENOSPC and read as test failures. The exit stays 3 (SPEC v5.4
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
        assert rec["stage2"] == [{"step": "unit A", "result": "disk", "seconds": 3.0},
                                 {"step": "unit B", "result": "fail", "seconds": 1.0}], rec["stage2"]
        said = out.getvalue()
        assert "DISK: unit A stopped on a full disk (No space left on device)" in said, said
        assert "not a test failure" in said and "unit B" not in said.split("DISK:", 1)[1], said
        assert "CACHE:" not in said, said


def test_stage2_steps_records_a_compile_cache_step_as_cache_and_says_it_is_no_test_failure():
    # The shared Swift compile cache stopped a step; the exit stays 3, the record and the
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
        assert rec["stage2"] == [{"step": "unit A", "result": "cache", "seconds": 3.0},
                                 {"step": "unit B", "result": "pass", "seconds": 1.0}], rec["stage2"]
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
                patch.object(cl, "check_work_order", side_effect=lambda team, rec: calls.append(("check", rec["wo"]))
                             or ["docs/x.md"]):
            cl.checked_members(team, ["w1", "w2"])
        assert calls == [("put back", "w1"), ("put back", "w2"), ("check", "w1"), ("check", "w2")], calls


def test_stage_admission_refuses_marker():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        marker(qdir)
        try:
            with cl.stage_admit("Stage 2", "check of a", qdir=qdir):
                raise AssertionError("admitted while restart pending")
        except cl.RestartPending:
            pass
        assert not list((qdir.parent / "restart" / "stages").glob("*.json"))


def test_live_stages_removes_dead_admissions():
    with tempfile.TemporaryDirectory() as tmp:
        rdir = Path(tmp) / "restart"
        stages = rdir / "stages"
        stages.mkdir(parents=True)
        (stages / "live.json").write_text(json.dumps({"pid": 10, "stage": "Stage 2", "name": "check of a", "started": 1}))
        (stages / "dead.json").write_text(json.dumps({"pid": 11, "stage": "Stage 5", "name": "recheck of b", "started": 1}))
        assert cl.live_stages(rdir, alive=lambda pid: pid == 10) == ["Stage 2 check of a"]
        assert not (stages / "dead.json").exists() and (stages / "live.json").exists()


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
    # A test that imported vendored code left __pycache__ in land/validate for the next run.
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        assert cl.team_env(team)["PYTHONDONTWRITEBYTECODE"] == "1"
        team.m["env"] = {"PYTHONDONTWRITEBYTECODE": ""}
        assert cl.team_env(team)["PYTHONDONTWRITEBYTECODE"] == ""


def test_restart_request_records_tip_files_and_waited():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        cl.request_buildq_restart(qdir, "0123456789abcdef", ["share/codeteam_hang.py"])
        row = json.loads((qdir.parent / "restart" / "buildq.json").read_text())
        assert row["tip"] == "0123456789abcdef" and row["files"] == ["share/codeteam_hang.py"]
        assert row["waited"] == [] and row["requested"] and isinstance(row["requested_ts"], (int, float))


def test_landing_jobs_only_queued_and_running_landing_jobs():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        for ticket, state, landing in (("q", "queued", "1"), ("r", "running", "1"),
                                       ("done", "done", "1"), ("other", "running", "0"), (".hidden", "queued", "1")):
            job(qdir, ticket, state, landing)
        assert set(cl.landing_jobs_running(qdir)) == {"q (unit A)", "r (unit A)"}


def test_restart_waits_for_stages_and_jobs_and_announces_all():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        p = marker(qdir)
        stages = p.parent / "stages"
        stages.mkdir()
        stage = stages / "live.json"
        stage.write_text(json.dumps({"pid": 10, "stage": "Stage 2", "name": "check of a", "started": 1}))
        job(qdir, "t1", "queued", "1")
        kick = Mock()
        assert cl.buildq_restart_step(team, qdir=qdir, kickstart=kick, alive=lambda pid: True) is False
        assert p.exists() and not kick.called
        stage.unlink()
        assert cl.buildq_restart_step(team, qdir=qdir, kickstart=kick, alive=lambda pid: True) is False
        (qdir / "t1.json").unlink()
        assert cl.buildq_restart_step(team, qdir=qdir, kickstart=kick, alive=lambda pid: True) is True
        kick.assert_called_once()
        assert not p.exists()
        to, kind, text = team.notify.call_args.args
        assert (to, kind) == ("Skippy", "NOTE")
        assert all(s in text for s in ("Restarted com.codeteam.codeteam-buildq", "0123456789", "Stage 2 check of a", "t1 (unit A)")), text


def test_restart_failure_posts_and_releases_marker():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        p = marker(qdir)
        kick = Mock(side_effect=OSError("fake failure"))
        assert cl.buildq_restart_step(team, qdir=qdir, kickstart=kick, alive=lambda pid: False) is True
        assert not p.exists()
        assert "Could not restart com.codeteam.codeteam-buildq at 0123456789: fake failure; restart it by hand" in team.notify.call_args.args[2]


def test_restart_without_marker_does_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        kick = Mock()
        assert cl.buildq_restart_step(team, qdir=root / "queue", kickstart=kick, alive=lambda pid: False) is False
        kick.assert_not_called()
        team.notify.assert_not_called()


def stage2_case(self_driven):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        p = marker(qdir)
        record = {"wo": "w", "zone": "A", "tree": str(root), "branch": "w"}
        polls = []

        def fake_sleep(*_):
            # A wait that never ends fails here instead of hanging the run.
            polls.append(1)
            if len(polls) > 50:
                raise AssertionError("Stage 2 still waiting after 50 polls")
            if p.exists() and not self_driven:
                p.unlink()
        sleep = Mock(side_effect=fake_sleep)
        kick = Mock()
        real_step = getattr(cl, "buildq_restart_step", None)

        def step(t):
            return real_step(t, qdir=qdir, kickstart=kick, alive=lambda pid: False)
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(qdir)}), patch.object(cl, "own_checkout", return_value=self_driven), \
                patch.object(cl, "buildq_restart_step", side_effect=step, create=True), patch.object(cl.time, "sleep", sleep), \
                patch.object(cl, "checked_members", return_value=[(record, False)]) as checked, \
                patch.object(cl, "out", return_value="hash"), patch.object(cl, "merge_checked_base"), \
                patch.object(cl, "changed_files", return_value=[]), patch.object(cl, "check_combined_members", return_value=(["A"], [])), \
                patch.object(cl, "queue_notices"), patch.object(cl, "stage3_record", return_value={"wo": "w", "reviewers": {}, "seen": {}, "state": "land"}), contextlib.redirect_stderr(io.StringIO()) as err, \
                contextlib.redirect_stdout(io.StringIO()):
            cl.cmd_land(team, SimpleNamespace(wo="w", with_=[], untested=False))
        checked.assert_called_once()
        assert not p.exists(), "Stage 2 did not wait for restart"
        assert "buildq.json" in err.getvalue(), err.getvalue()
        assert len(list((team.dir / "queue").glob("*.json"))) == 1
        if self_driven:
            kick.assert_called_once()
        else:
            sleep.assert_called()


def test_held_stage2_waits_until_marker_released():
    stage2_case(False)


def test_held_stage2_drives_restart_without_another_runner():
    stage2_case(True)


def test_held_stage5_skips_pending_row():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        marker(qdir)
        row = {"wo": "w", "M": "0123456789abcdef"}
        (team.dir / "recheck.jsonl").write_text(json.dumps(row) + "\n")
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(qdir)}), patch.object(cl, "halted", return_value=False), \
                patch.object(cl, "recheck_one") as one:
            cl.cmd_recheck_run(team, SimpleNamespace(once=True))
        one.assert_not_called()
        assert cl.read_recheck(team) == [row]


def test_held_local_stage6_skips_validation():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        marker(qdir)
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(qdir)}), patch.object(cl, "own_checkout", return_value=False), \
                patch.object(cl, "halted", return_value=False), patch.object(cl, "stage6_target", return_value="0123456789abcdef"), \
                patch.object(cl, "alpha_cfg", return_value={"local": True}), patch.object(cl, "validate_due", return_value=True), \
                patch.object(cl, "validate_one", return_value={"commit": "0123456789abcdef", "result": "fail", "tests": []}) as one:
            cl.cmd_validate_run(team, SimpleNamespace(once=True))
        one.assert_not_called()


def test_held_remote_stage6_still_runs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        team = make_team(root)
        qdir = root / "queue"
        marker(qdir)
        result = {"commit": "0123456789abcdef", "result": "fail", "tests": []}
        with patch.dict(os.environ, {"CODETEAM_QUEUE_DIR": str(qdir)}), patch.object(cl, "own_checkout", return_value=False), \
                patch.object(cl, "halted", return_value=False), patch.object(cl, "stage6_target", return_value="0123456789abcdef"), \
                patch.object(cl, "alpha_cfg", return_value={"local": False}), patch.object(cl, "validate_due", return_value=True), \
                patch.object(cl, "validate_one", return_value=result) as one:
            cl.cmd_validate_run(team, SimpleNamespace(once=True))
        one.assert_called_once()


def test_halted_queue_runner_drives_restart_before_halted_check():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        events = []
        with patch.object(cl, "own_checkout", return_value=True), \
                patch.object(cl, "buildq_restart_step", side_effect=lambda *_: events.append("restart"), create=True), \
                patch.object(cl, "halted", side_effect=lambda *_: events.append("halted") or True):
            cl.cmd_queue_run(team, SimpleNamespace(once=True))
        assert events == ["restart", "halted"], events


def test_validate_runner_drives_restart_before_own_runner_restart():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        events = []
        with patch.object(cl, "own_checkout", return_value=True), \
                patch.object(cl, "buildq_restart_step", side_effect=lambda *_: events.append("buildq"), create=True), \
                patch.object(cl, "runner_restart", side_effect=lambda *_: events.append("runner") or True):
            cl.cmd_validate_run(team, SimpleNamespace(once=True))
        assert events == ["buildq", "runner"], events


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




















if __name__ == "__main__":
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
