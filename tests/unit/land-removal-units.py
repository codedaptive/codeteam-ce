#!/usr/bin/env -S python3 -u
"""Isolated landing decisions: reviewed entries, prelanding review, and unlimited waits."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

HOME = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)


def test_runner_waits_for_every_job_without_a_limit() -> None:
    jobs = [Mock(returncode=0), Mock(returncode=1), Mock(returncode=0)]
    jobs[0].communicate.return_value = ("checked",)
    jobs[1].communicate.return_value = ("wrong answer",)
    jobs[2].communicate.return_value = ("tested",)
    with patch.object(cl.subprocess, "Popen", side_effect=jobs) as start, \
            patch.object(cl.time, "time", return_value=100):
        ok, lines = cl.run_steps(Path("tree"), [("type check", "check"), ("tests A", "a"), ("tests B", "b")], {})
    assert ok is False
    assert lines == ["PASS type check (0 s)", "FAIL tests A (0 s)", "  | wrong answer", "PASS tests B (0 s)"]
    assert [call.args[0] for call in start.call_args_list] == ["check", "a", "b"]
    for job in jobs:
        job.communicate.assert_called_once_with()
        job.kill.assert_not_called()
        job.terminate.assert_not_called()


def test_queue_skips_held_and_pending_entries() -> None:
    with tempfile.TemporaryDirectory(prefix="land-ready-unit-") as tmp:
        directory = Path(tmp)
        (directory / "queue").mkdir()
        for filename, wo, hold in (("00-pending.json", "pending", False), ("03-new.json", "new", False), ("01-held.json", "held", True),
                                   ("02-old.json", "old", False)):
            (directory / "queue" / filename).write_text(json.dumps({"wo": wo, "wos": [wo], "hold": hold, "review": "pending" if wo == "pending" else "land"}))
        team = SimpleNamespace(dir=directory, repo=Path("repo"))
        with contextlib.ExitStack() as stack:
            for name in ("prune_queue", "features_due", "clean_idle"):
                stack.enter_context(patch.object(cl, name))
            watch = stack.enter_context(patch.object(cl, "results_watch", create=True))
            stack.enter_context(patch.object(cl, "halted", return_value=False))
            stack.enter_context(patch.object(cl, "Lock", side_effect=lambda team: contextlib.nullcontext()))
            land = stack.enter_context(patch.object(cl, "land_entry"))
            cl.cmd_queue_run(team, SimpleNamespace(once=True))
            land.assert_called_once_with(team, directory / "queue" / "02-old.json")
            watch.assert_not_called()


def test_queue_runner_merges_one_entry_at_a_time_until_idle() -> None:
    team = SimpleNamespace(c=lambda key, default: default, dir=Path(tempfile.mkdtemp()), repo=Path("repo"))   # no restart marker
    first, second = Mock(), Mock()
    first.read_text.return_value = second.read_text.return_value = '{"review": "land"}'
    with contextlib.ExitStack() as stack:
        for name in ("prune_queue", "features_due", "clean_idle"):
            stack.enter_context(patch.object(cl, name))
        stack.enter_context(patch.object(cl, "results_watch", create=True))
        stack.enter_context(patch.object(cl, "halted", return_value=False))
        stack.enter_context(patch.object(cl, "Lock", side_effect=lambda team: contextlib.nullcontext()))
        stack.enter_context(patch.object(cl, "entries", side_effect=[[first, second], [second], []]))
        stack.enter_context(patch.object(cl.time, "time", return_value=100))
        idle = stack.enter_context(patch.object(cl.time, "sleep", side_effect=RuntimeError("idle")))
        land = stack.enter_context(patch.object(cl, "land_entry"))
        try:
            cl.cmd_queue_run(team, SimpleNamespace(once=False))
        except RuntimeError as exc:
            assert str(exc) == "idle"
        else:
            raise AssertionError("runner did not reach its idle poll")
        assert [call.args[1] for call in land.call_args_list] == [first, second]
        idle.assert_called_once_with(15)


def test_public_api_and_security_changes_queue_for_review() -> None:
    with tempfile.TemporaryDirectory(prefix="land-submit-unit-") as tmp:
        directory = Path(tmp)
        (directory / "queue").mkdir()
        (directory / "reviews").mkdir()
        rec = {"wo": "api", "zone": "orc", "tree": "tree"}
        team = SimpleNamespace(dir=directory, repo=Path("repo"), integration="integration", landing="landing", m={"assistants": [{"name": "Perkins"}]}, cfg={}, manifest=Path("team.toml"), wo=lambda wo: rec,
                               zones={}, c=lambda key, default: ["A/auth/*"] if key == "security_paths" else default, save_wo=Mock(), notify=Mock())
        with contextlib.ExitStack() as stack:
            collaborators = {"entry_path": None, "check_work_order": ["A/auth/store.rs"], "current_units": True,
                             "changed_files": ["A/auth/store.rs"], "reach": ["A", "B"],
                             "check_integration": ["A", "B"], "interface_changes": {"open": ["B"]},
                             "api_delta": {"removed": ["fn open"], "changed": [], "added": []},
                             "now": "queued-time", "tag_wo": None,
                             "git": SimpleNamespace(returncode=0)}
            for name, result in collaborators.items():
                stack.enter_context(patch.object(cl, name, return_value=result))
            stack.enter_context(patch.object(cl, "out", side_effect=lambda repo, *a: "A/auth/store.rs" if a[0] == "diff-tree" else "tip"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            cl.cmd_land(team, SimpleNamespace(wo="api", with_=[], untested=False))
        entry = json.loads(next((directory / "queue").iterdir()).read_text())
        assert entry == {"wos": ["api"], "wo": "api", "tip": "tip", "base": "tip", "zones": ["A", "B"],
                         "queued": "queued-time", "state": "waiting", "review": "pending"}
        assert rec["api"]["removed"] == ["fn open"]
        assert not {"blocking", "perkins", "review"} & rec.keys()
        assert [call.args[1] for call in team.notify.call_args_list] == ["NOTE", "REQUEST", "REQUEST"]
        assert [call.args[0] for call in team.notify.call_args_list] == ["Coord-B", "Kong", "Perkins"]


def test_feature_records_review_after() -> None:
    team = SimpleNamespace(cfg={"review_after": {"enabled": True}})
    rec = {"wo": "api", "zone": "A", "landed_commit": "landed-hash"}
    with patch.object(cl, "load_feature", return_value={"feature": "api", "landed": []}), \
            patch.object(cl, "save_feature") as save, patch.object(cl, "features_due"), \
            patch.object(cl, "now", return_value="landed-time"):
        cl.after_landing(team, [rec])
    assert save.call_args.args[1]["landed"] == [{"wo": "api", "zone": "A", "hash": "landed-hash",
                                                "time": "landed-time", "review": "before"}]


def test_team_environment_does_not_inherit_test_time_limits() -> None:
    team = SimpleNamespace(root=Path("root"), dir=Path("land"), manifest=Path("team.toml"), cfg={},
                           m={"env": {"TMPDIR": "scratch"}})
    with patch.dict(os.environ, {"ZONE_TEST_FLAGS": "--timeout 1", "ZONE_TEST_ONE_FLAGS": "--timeout 2"}, clear=True):
        env = cl.team_env(team)
    assert env["ZONE_TEST_FLAGS"] == ""
    assert env["ZONE_TEST_ONE_FLAGS"] == ""
    assert env["GROUP"] == "unit"
    assert env["CODETEAM_TEST_GROUP"] == "unit"
    assert env["ZONE_JOB_WAIT"] == "0"


def test_alpha_suite_has_no_runtime_limit() -> None:
    with tempfile.TemporaryDirectory(prefix="land-alpha-unit-") as tmp:
        team = SimpleNamespace(repo=Path("repo"), dir=Path(tmp), zones={}, cfg={})
        config = {"host": "alpha", "path": "clone", "suite": "tests", "toolchain": ["echo toolchain"]}
        with patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
                patch.object(cl, "ensure_land_check", return_value=None, create=True), \
                patch.object(cl, "toolchain_fp", return_value="fp"), \
                patch.object(cl, "ssh", return_value=SimpleNamespace(stdout='{"hash":"hash","result":"pass"}')) as ssh:
            result = cl.check_at(team, config, "hash", "validation")
        assert result["result"] == "pass"
        assert ssh.call_args.kwargs == {}
        assert "CODETEAM_TEST_GROUP=validation" in ssh.call_args.args[1]
        assert "~/bin/land-check hash tests 'echo toolchain' fp" in ssh.call_args.args[1]


def test_hung_job_fails_even_with_a_success_exit() -> None:
    job = Mock(returncode=0)
    job.communicate.return_value = ("progress\nzone-test: HUNG\n",)
    with patch.object(cl.subprocess, "Popen", return_value=job), patch.object(cl.time, "time", return_value=0):
        ok, lines = cl.run_steps("tree", [("tests A", "test")], {})
    assert ok is False
    assert lines == ["HUNG tests A (0 s)", "  | progress", "  | zone-test: HUNG"]


def test_units_pass_requires_all_zero_codes() -> None:
    assert cl.units_pass([]) is True
    assert cl.units_pass([0, 0]) is True
    assert cl.units_pass([0, 1]) is False
    assert cl.units_pass([0, 2]) is False


def test_manifest_environment_keeps_both_explicit_test_flags() -> None:
    team = SimpleNamespace(root=Path("root"), dir=Path("land"), manifest=Path("team.toml"), cfg={},
                           m={"env": {"TMPDIR": "scratch", "ZONE_TEST_ONE_FLAGS": "custom-one",
                                      "ZONE_TEST_FLAGS": "custom-all"}})
    with patch.dict(os.environ, {"ZONE_TEST_FLAGS": "--timeout 1", "ZONE_TEST_ONE_FLAGS": "--timeout 2"}, clear=True):
        env = cl.team_env(team)
    assert env["ZONE_TEST_ONE_FLAGS"] == "custom-one"
    assert env["ZONE_TEST_FLAGS"] == "custom-all"


def test_revert_mainline_is_used_only_for_two_parents() -> None:
    assert cl.revert_args(["base"]) == ["revert", "--no-edit"]
    assert cl.revert_args(["integration", "checked-tip"]) == ["revert", "-m", "1", "--no-edit"]
    assert cl.revert_args([]) == ["revert", "--no-edit"]
    assert cl.revert_args(["first", "second", "third"]) == ["revert", "--no-edit"]


def lane_record_key(group: str) -> str:
    """The key zone_tests submits for a lane zone with its own `test` command, run in `group`."""
    team = SimpleNamespace(m={"lanes": [{"name": "orc", "test": "tests/run.sh"}]})
    [(_, cmd)] = cl.zone_tests(team, "tree", "orc", "dev", group=group)
    words = cl.shlex.split(cmd)
    return words[words.index("--key") + 1]


def test_unit_key_query_uses_make_expansion_for_each_unit_folder() -> None:
    team = SimpleNamespace(m={})
    with patch.object(cl, "test_folders", return_value=["A", "B"]) as folders, \
            patch.object(cl, "team_env", return_value={"GROUP": "unit"}), \
            patch.object(cl.subprocess, "run", side_effect=[
                SimpleNamespace(returncode=0, stdout="CODETEAM-UNIT-KEY=one A owns=src\n"),
                SimpleNamespace(returncode=1, stdout="")]) as make:
        assert cl.unit_step_keys(team, Path("tree"), "zone") is None
    folders.assert_called_once_with(team, Path("tree"), "zone", "unit")
    assert [call.args[0][-2] for call in make.call_args_list] == ["DIR=A", "DIR=B"]
    for call in make.call_args_list:
        assert call.args[0][3:5] == ["-f", "-"]
        assert call.kwargs["input"] == "codeteam-unit-key:\n\t@$(info CODETEAM-UNIT-KEY=$(strip $(ZONE_TEST_ONE_KEY))):\n"
        assert call.kwargs["env"] == {"GROUP": "unit"}
        assert call.kwargs["cwd"] == Path("tree")


def test_unit_step_folders_share_skip_rules_with_zone_tests() -> None:
    team = SimpleNamespace(m={"lanes": [{"name": "zone", "path": "A"}]}, zones={"zone": ["A", "B", "notes"]},
                           c=lambda key, default: ["B"] if key == "skip_tests" else default)
    with patch.object(cl, "test_folder", side_effect=lambda tree, folder, lane: folder != "notes"):
        assert cl.test_folders(team, "tree", "zone", "unit") == ["A"]
        assert cl.zone_tests(team, "tree", "zone", "dev") == [
            ("tests zone (A)", "make --no-print-directory zone-test-one DIR=A CLASS=dev")]
        assert cl.test_folders(team, "tree", "zone", "integration") == ["A", "B"]


def test_an_owned_folder_with_no_package_is_a_wall_not_a_test_root() -> None:
    # acme-mgr owns docs/specs/acme-mgr; its own path is tested, the spec folder is not.
    with tempfile.TemporaryDirectory(prefix="land-owned-") as tmp:
        tree = Path(tmp)
        (tree / "apps" / "acme-mgr").mkdir(parents=True)
        (tree / "docs" / "specs" / "acme-mgr").mkdir(parents=True)
        (tree / "libs" / "SQLCipher").mkdir(parents=True)
        (tree / "libs" / "SQLCipher" / "Package.swift").write_text("")
        team = SimpleNamespace(m={"lanes": [{"name": "acme-mgr", "path": "apps/acme-mgr", "owns": ["docs/specs/acme-mgr",
                                                                                          "libs/SQLCipher"]}]},
                               zones={"acme-mgr": ["apps/acme-mgr", "docs/specs/acme-mgr", "libs/SQLCipher"]},
                               c=lambda key, default: default)
        assert cl.test_folders(team, tree, "acme-mgr", "unit") == ["apps/acme-mgr", "libs/SQLCipher"]


def test_landing_consumes_entry_before_failed_cleanup_and_finishes() -> None:
    with tempfile.TemporaryDirectory(prefix="land-cleanup-unit-") as tmp:
        directory = Path(tmp)
        entry_path = directory / "entry.json"
        entry_path.write_text(json.dumps({"wo": "work", "tip": "checked-tip", "base": "base", "zones": ["A"], "review": "land"}))
        record_path = directory / "work.json"
        record_path.write_text("{}")
        rec = {"wo": "work", "zone": "A", "tree": "tree", "branch": "wo/A/work"}
        team = SimpleNamespace(repo=Path("repo"), dir=directory, integration="integration", landing="landing", lab=False, zones={"A": ["A"]},
                               wo=lambda wo: rec, wo_file=lambda wo: record_path, save_wo=Mock(), log=Mock(),
                               c=lambda key, default: default)
        calls = []

        def git(repo, *args, **kwargs):
            calls.append(args)
            if args[0] == "merge-tree":
                return SimpleNamespace(returncode=0, stdout="merged-tree\n")
            if args[0] == "commit-tree":
                return SimpleNamespace(returncode=0, stdout="landed-merge\n")
            assert not entry_path.exists(), "a moved integration must consume its entry before cleanup"
            if args[0] in ("worktree", "branch"):
                assert kwargs == {"check": False}
                return SimpleNamespace(returncode=1, stdout="", stderr="cleanup refused")
            return SimpleNamespace(returncode=0)

        def move(team, tip, old):
            assert entry_path.exists()
            assert (tip, old) == ("landed-merge", "old-landing")
            return True

        with patch.object(cl, "integration_holders", return_value=[]), \
                patch.object(cl, "out", side_effect=["old-landing", "own commits"]), \
                patch.object(cl, "git", side_effect=git), patch.object(cl, "move_landing", side_effect=move), \
                patch.object(cl, "intervening_landings", return_value=[]), \
                patch.object(cl, "landing_bookkeeping") as bookkeeping, \
                patch.object(cl, "now", return_value="landed-time"), contextlib.redirect_stdout(io.StringIO()):
            assert cl.land_entry(team, entry_path) == 0
        assert not entry_path.exists()
        assert record_path.with_suffix(".landed.json").exists()
        assert rec["landed_commit"] == "landed-merge"
        assert calls[-2:] == [("worktree", "remove", "--force", "tree"), ("branch", "-D", "wo/A/work")]
        rows = [call.args[0] for call in team.log.call_args_list]
        assert rows[:2] == [
            {"time": "landed-time", "wos": ["work"], "cleanup_error": "worktree remove --force tree", "detail": "cleanup refused"},
            {"time": "landed-time", "wos": ["work"], "cleanup_error": "branch -D wo/A/work", "detail": "cleanup refused"}]
        assert rows[2]["hash"] == "landed-merge"
        bookkeeping.assert_called_once_with(team, [rec], [rows[2]])


def test_docs_overlap_does_not_require_recheck() -> None:
    assert cl.overlapping({"a": ["src/a"]}, [("guide", ["src/a/guide.md"]), ("sibling", ["src/ab/x.py"])],
                          ["a"], [".md"]) == []


def test_lane_record_keys() -> None:
    team = SimpleNamespace(m={"lanes": [{"name": "orc", "test": "tests/run.sh"}]})
    assert lane_record_key("unit") == "lane orc"
    assert lane_record_key("integration") == "lane orc test-group=integration"
    assert cl.unit_step_keys(team, Path("tree"), "orc") == ["lane orc"]


def test_current_units_requires_all_scheduled_records() -> None:
    tree = Path("tree")
    for codes, expected in (([0, 0], True), ([0, 2], False), ([2, 0], False), ([0, 1], False)):
        with patch.object(cl, "unit_step_keys", return_value=["one A owns=", "lane z"]), \
                patch.object(cl, "out", return_value="abc123"), \
                patch.object(cl, "commit_record", side_effect=codes, create=True) as record:
            assert cl.current_units(Mock(), tree, "zone") is expected, codes
        if expected:
            assert record.call_args_list == [((tree, "abc123", "one A owns="),), ((tree, "abc123", "lane z"),)]


def test_entry_current_requires_all_stage_two_fields() -> None:
    checked = {"wo": "work", "tip": "tip", "base": "base", "zones": [], "review": "land"}
    assert cl.entry_current(checked) is True
    assert cl.entry_current({"wos": ["work"], "queued": "queued-time", "state": "waiting"}) is False
    for missing in ("wo", "tip", "base", "zones", "review"):
        assert cl.entry_current({key: value for key, value in checked.items() if key != missing}) is False, missing


def test_prune_moves_unchecked_entries_and_sends_one_note() -> None:
    with tempfile.TemporaryDirectory(prefix="land-stale-unit-") as tmp:
        directory = Path(tmp)
        (directory / "queue").mkdir()
        (directory / "wo").mkdir()
        for wo in ("old-a", "old-b", "checked"):
            (directory / "wo" / f"{wo}.json").write_text("{}")
        (directory / "wo" / "old-a.landed.json").write_text("{}")
        for filename, wo in (("01-old.json", "old-a"), ("02-old.json", "old-b")):
            (directory / "queue" / filename).write_text(json.dumps(
                {"wos": [wo], "queued": "queued-time", "state": "waiting"}))
        current = directory / "queue" / "03-checked.json"
        current.write_text(json.dumps({"wos": ["checked"], "wo": "checked", "tip": "tip", "base": "base", "zones": [], "review": "land"}))
        team = SimpleNamespace(dir=directory, wo_file=lambda wo: directory / "wo" / f"{wo}.json",
                               c=lambda key, default=None: default, notify=Mock())
        cl.prune_queue(team)
        assert sorted(path.name for path in (directory / "queue-stale").iterdir()) == ["01-old.json", "02-old.json"]
        assert sorted(path.name for path in (directory / "queue").iterdir()) == ["03-checked.json"]
        team.notify.assert_called_once()
        recipient, kind, text = team.notify.call_args.args
        assert (recipient, kind) == ("orc", "NOTE")
        assert "old-a" in text and "old-b" in text
        assert "run `land` again" in text and "Stage 2" in text and "Stage 3" in text
        assert "no current record" in text and str(directory / "queue-stale") in text


def test_land_entry_refuses_unchecked_entry_before_record_or_git() -> None:
    with tempfile.TemporaryDirectory(prefix="land-refuse-unit-") as tmp:
        directory = Path(tmp)
        (directory / "queue").mkdir()
        entry = directory / "queue" / "old.json"
        entry.write_text(json.dumps({"wos": ["old"], "queued": "queued-time", "state": "waiting"}))
        team = SimpleNamespace(dir=directory, wo=Mock(side_effect=AssertionError("must not read a record")))
        stderr = io.StringIO()
        with patch.object(cl, "git", side_effect=AssertionError("must not use git")) as git, \
                contextlib.redirect_stderr(stderr):
            assert cl.land_entry(team, entry) == 5
        team.wo.assert_not_called()
        git.assert_not_called()
        assert not entry.exists()
        assert (directory / "queue-stale" / "old.json").is_file()
        assert stderr.getvalue() == "old.json: a queue entry without current Stage 2/3 records; run land again for old\n"


def test_land_entry_refuses_even_when_set_aside_fails() -> None:
    with tempfile.TemporaryDirectory(prefix="land-stale-blocked-unit-") as tmp:
        directory = Path(tmp)
        (directory / "queue").mkdir()
        (directory / "queue-stale").write_text("blocked")
        entry = directory / "queue" / "old.json"
        entry.write_text(json.dumps({"wos": ["old"], "queued": "queued-time", "state": "waiting"}))
        team = SimpleNamespace(dir=directory, wo=Mock(side_effect=AssertionError("must not read a record")))
        stderr = io.StringIO()
        with patch.object(cl, "git", side_effect=AssertionError("must not use git")) as git, \
                contextlib.redirect_stderr(stderr):
            assert cl.land_entry(team, entry) == 5
        assert "without current Stage 2/3 records" in stderr.getvalue()
        assert entry.is_file()
        assert (directory / "queue-stale").read_text() == "blocked"
        team.wo.assert_not_called()
        git.assert_not_called()


def test_land_one_prunes_unchecked_entry_before_lookup() -> None:
    with tempfile.TemporaryDirectory(prefix="land-one-stale-unit-") as tmp:
        directory = Path(tmp)
        (directory / "queue").mkdir()
        (directory / "wo").mkdir()
        (directory / "wo" / "old.json").write_text("{}")
        entry = directory / "queue" / "old.json"
        entry.write_text(json.dumps({"wos": ["old"], "queued": "queued-time", "state": "waiting"}))
        team = SimpleNamespace(dir=directory, wo_file=lambda wo: directory / "wo" / f"{wo}.json",
                               c=lambda key, default=None: default, notify=Mock())
        stderr = io.StringIO()
        with patch.object(cl, "Lock", side_effect=lambda team: contextlib.nullcontext()), \
                patch.object(cl, "land_entry") as land, contextlib.redirect_stderr(stderr):
            try:
                cl.cmd_land_one(team, SimpleNamespace(wo="old"))
            except SystemExit as exc:
                assert exc.code == 5
            else:
                raise AssertionError("land-one must refuse an unchecked entry")
        assert stderr.getvalue() == "old is not queued\n"
        land.assert_not_called()
        assert not entry.exists()
        assert (directory / "queue-stale" / "old.json").is_file()


def test_queue_runner_prunes_unchecked_entry_before_checked_entry() -> None:
    with tempfile.TemporaryDirectory(prefix="land-ready-stale-unit-") as tmp:
        directory = Path(tmp)
        (directory / "queue").mkdir()
        (directory / "wo").mkdir()
        for wo in ("old", "new"):
            (directory / "wo" / f"{wo}.json").write_text("{}")
        (directory / "queue" / "01-old.json").write_text(json.dumps(
            {"wos": ["old"], "queued": "queued-time", "state": "waiting"}))
        current = directory / "queue" / "02-new.json"
        current.write_text(json.dumps({"wos": ["new"], "wo": "new", "tip": "tip", "base": "base", "zones": [], "review": "land"}))
        team = SimpleNamespace(dir=directory, wo_file=lambda wo: directory / "wo" / f"{wo}.json",
                               c=lambda key, default=None: default, notify=Mock(), repo=Path("repo"))
        with contextlib.ExitStack() as stack:
            for name in ("features_due", "clean_idle"):
                stack.enter_context(patch.object(cl, name))
            stack.enter_context(patch.object(cl, "results_watch", create=True))
            stack.enter_context(patch.object(cl, "halted", return_value=False))
            stack.enter_context(patch.object(cl, "Lock", side_effect=lambda team: contextlib.nullcontext()))
            land = stack.enter_context(patch.object(cl, "land_entry"))
            cl.cmd_queue_run(team, SimpleNamespace(once=True))
        land.assert_called_once_with(team, current)
        assert (directory / "queue-stale" / "01-old.json").is_file()
        assert not (directory / "queue" / "01-old.json").exists()
        team.notify.assert_called_once()


def test_prune_unchecked_entries_ignores_notification_failure() -> None:
    with tempfile.TemporaryDirectory(prefix="land-note-stale-unit-") as tmp:
        directory = Path(tmp)
        (directory / "queue").mkdir()
        (directory / "wo").mkdir()
        (directory / "wo" / "old.json").write_text("{}")
        entry = directory / "queue" / "old.json"
        entry.write_text(json.dumps({"wos": ["old"], "queued": "queued-time", "state": "waiting"}))
        team = SimpleNamespace(dir=directory, wo_file=lambda wo: directory / "wo" / f"{wo}.json",
                               c=lambda key, default=None: default, notify=Mock(side_effect=RuntimeError("notice failed")))
        cl.prune_queue(team)
        assert not entry.exists()
        assert (directory / "queue-stale" / "old.json").is_file()
        team.notify.assert_called_once()


def test_queue_runner_polls_after_refused_entry() -> None:
    team = SimpleNamespace(c=lambda key, default: default, dir=Path(tempfile.mkdtemp()), repo=Path("repo"))   # no restart marker
    entry = Mock()
    entry.read_text.return_value = '{"wos": ["old"], "queued": "queued-time", "state": "waiting", "review": "land"}'
    with contextlib.ExitStack() as stack:
        for name in ("prune_queue", "features_due", "clean_idle"):
            stack.enter_context(patch.object(cl, name))
        stack.enter_context(patch.object(cl, "results_watch", create=True))
        stack.enter_context(patch.object(cl, "halted", return_value=False))
        stack.enter_context(patch.object(cl, "Lock", side_effect=lambda team: contextlib.nullcontext()))
        stack.enter_context(patch.object(cl, "entries", return_value=[entry]))
        stack.enter_context(patch.object(cl.time, "time", return_value=100))
        idle = stack.enter_context(patch.object(cl.time, "sleep", side_effect=RuntimeError("idle")))
        land = stack.enter_context(patch.object(cl, "land_entry", side_effect=[
            5, AssertionError("refused entry retried before idle poll")]))
        try:
            cl.cmd_queue_run(team, SimpleNamespace(once=False))
        except RuntimeError as exc:
            assert str(exc) == "idle"
        else:
            raise AssertionError("runner did not reach its idle poll")
        land.assert_called_once_with(team, entry)
        idle.assert_called_once_with(15)


failed = 0
for test in (test_alpha_suite_has_no_runtime_limit, test_runner_waits_for_every_job_without_a_limit,
             test_queue_skips_held_and_pending_entries, test_queue_runner_merges_one_entry_at_a_time_until_idle,
             test_public_api_and_security_changes_queue_for_review, test_feature_records_review_after,
             test_team_environment_does_not_inherit_test_time_limits, test_hung_job_fails_even_with_a_success_exit,
             test_units_pass_requires_all_zero_codes, test_manifest_environment_keeps_both_explicit_test_flags,
             test_revert_mainline_is_used_only_for_two_parents, test_lane_record_keys,
             test_current_units_requires_all_scheduled_records, test_unit_key_query_uses_make_expansion_for_each_unit_folder,
             test_unit_step_folders_share_skip_rules_with_zone_tests,
             test_landing_consumes_entry_before_failed_cleanup_and_finishes, test_docs_overlap_does_not_require_recheck,
             test_entry_current_requires_all_stage_two_fields, test_prune_moves_unchecked_entries_and_sends_one_note,
             test_land_entry_refuses_unchecked_entry_before_record_or_git, test_land_entry_refuses_even_when_set_aside_fails,
             test_land_one_prunes_unchecked_entry_before_lookup,
             test_queue_runner_prunes_unchecked_entry_before_checked_entry,
             test_an_owned_folder_with_no_package_is_a_wall_not_a_test_root,
             test_prune_unchecked_entries_ignores_notification_failure, test_queue_runner_polls_after_refused_entry):
    if len(sys.argv) > 1 and test.__name__ not in sys.argv[1:]:
        continue
    try:
        test()
        print(f"  PASS {test.__name__}")
    except Exception as exc:
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        failed += 1
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
