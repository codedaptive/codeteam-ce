#!/usr/bin/env python3
"""Unit contracts for reached checks, repository integration tests and landing sets."""
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, Mock, call, mock_open, patch

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_sets", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl_sets", loader)
cl = importlib.util.module_from_spec(spec)
with patch("subprocess.run", return_value=SimpleNamespace(stdout="")):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)


def team(cfg=None, env=None):
    obj = Mock()
    obj.cfg = cfg or {}
    obj.m = {"env": env or {}}
    obj.c.side_effect = lambda key, default: obj.cfg.get(key, default)
    obj.zones = {"A": ["a", "shared"], "B": ["b", "shared"]}
    obj.root = Path("/team")
    obj.repo = Path("/repo")
    obj.integration = "integration"
    obj.landing = "landing"
    obj.lab = False
    obj.manifest = Path("/team.toml")
    obj.dir = Path(tempfile.mkdtemp(prefix="land-set-unit-"))
    for name in ("queue", "reviews", "wo"):
        (obj.dir / name).mkdir()
    return obj


class Checks(unittest.TestCase):
    def test_make_check_success(self):
        self.assertTrue(cl.make_has_check(0, ""))

    def test_make_check_no_rule(self):
        self.assertFalse(cl.make_has_check(2, "make: No rule to make target 'check'."))

    def test_make_check_broken_is_still_a_check(self):
        self.assertTrue(cl.make_has_check(2, "syntax error"))

    def test_has_zone_check_manifest_or_make(self):
        self.assertEqual([cl.has_zone_check("", False), cl.has_zone_check("/pc", False),
                          cl.has_zone_check("", True)], [False, True, True])

    def test_zone_check_worked_example_and_deduplication(self):
        self.assertEqual(cl.zone_check_steps({"A": ["a", "shared"], "B": ["b", "shared"]},
                                           ["A", "B"], "/zt", "/pc"),
                         [("compile A (a)", "ZONE_CHECK=1 ZONE_CHECK_CMD=/pc /zt check a"),
                          ("compile A (shared)", "ZONE_CHECK=1 ZONE_CHECK_CMD=/pc /zt check shared"),
                          ("compile B (b)", "ZONE_CHECK=1 ZONE_CHECK_CMD=/pc /zt check b")])

    def test_zone_check_empty_command_and_missing_zone(self):
        self.assertEqual(cl.zone_check_steps({"A": ["a"]}, ["missing", "A"], "/zt", ""),
                         [("compile A (a)", "ZONE_CHECK=1 ZONE_CHECK_CMD='' /zt check a")])
        self.assertEqual(cl.zone_check_steps({"A": ["a"]}, [], "/zt", ""), [])

    def test_compile_manifest_selects_reached_zone(self):
        obj = team({"gates": ""}, {"ZONE_CHECK_CMD": "{root}/checker"})
        with patch.object(cl, "run", return_value=SimpleNamespace(returncode=2, stderr="No rule to make target")), \
                patch.object(cl, "default_check", return_value="whole"):
            steps = cl.compile_steps(obj, Path("tree"), ["B"])
        zt = str(ROOT / "bin" / "zone-tool")
        self.assertEqual(steps, [("compile B (b)", f"ZONE_CHECK=1 ZONE_CHECK_CMD=/team/checker {zt} check b"),
                                 ("compile B (shared)", f"ZONE_CHECK=1 ZONE_CHECK_CMD=/team/checker {zt} check shared")])

    def test_compile_inherited_command_does_not_select_zone(self):
        obj = team({"gates": ""})
        with patch.dict(os.environ, {"ZONE_CHECK_CMD": "inherited"}), \
                patch.object(cl, "run", return_value=SimpleNamespace(returncode=2, stderr="No rule to make target")), \
                patch.object(cl, "default_check", return_value="whole"):
            self.assertEqual(cl.compile_steps(obj, Path("tree"), ["A"]), [("type check", "whole")])

    def test_compile_explicit_empty_disables_compile_but_keeps_gates(self):
        obj = team({"check": "", "gates": "gate {integration}"}, {"ZONE_CHECK_CMD": "/pc"})
        with patch.object(cl, "run", return_value=SimpleNamespace(returncode=0, stderr="")):
            self.assertEqual(cl.compile_steps(obj, Path("tree"), ["A"]), [("repo gates", "gate integration")])

    def test_compile_make_check_uses_zone(self):
        obj = team({"gates": ""})
        with patch.object(cl, "run", return_value=SimpleNamespace(returncode=0, stderr="")):
            self.assertEqual(cl.compile_steps(obj, Path("tree"), ["A"]),
                [("compile A (a)", f"ZONE_CHECK=1 ZONE_CHECK_CMD='' {ROOT / 'bin' / 'zone-tool'} check a"),
                 ("compile A (shared)", f"ZONE_CHECK=1 ZONE_CHECK_CMD='' {ROOT / 'bin' / 'zone-tool'} check shared")])

    def test_check_integration_compiles_reached_zones(self):
        obj = team()
        rec = {"tree": "tree", "files": ["a/x.py"]}
        with patch.object(cl, "duplicate_rulings", return_value=[]), \
                patch.object(cl, "reach", return_value=["B", "A"]), \
                patch.object(cl, "compile_steps", return_value=[]) as compile_, \
                patch.object(cl, "zone_tests", return_value=[]), \
                patch.object(cl, "repo_integration_steps", return_value=[], create=True), \
                patch.object(cl, "team_env", return_value={}), patch.object(cl, "run_steps", return_value=(True, [])):
            self.assertEqual(cl.check_integration(obj, rec, False), ["B", "A"])
        compile_.assert_called_once_with(obj, "tree", ["B", "A"])

    def test_compile_steps_finish_before_the_next_process_starts(self):
        obj = team()
        steps = [("compile A (a)", "first"), ("compile B (b)", "second")]
        events = []
        first, second = Mock(returncode=1), Mock(returncode=0)
        first.communicate.side_effect = lambda: events.append("finish first") or ("bad\n",)
        second.communicate.side_effect = lambda: events.append("finish second") or ("ok\n",)

        def start(command, **kwargs):
            events.append(f"start {command}")
            return {"first": first, "second": second}[command]

        with patch.object(cl, "duplicate_rulings", return_value=[]), \
                patch.object(cl, "reach", return_value=["A", "B"]), \
                patch.object(cl, "compile_steps", return_value=steps), \
                patch.object(cl, "team_env", return_value={}), \
                patch.object(cl, "run_steps", wraps=cl.run_steps) as run, \
                patch.object(cl.subprocess, "Popen", side_effect=start), \
                patch.object(cl.time, "time", side_effect=[10, 13, 20, 24]), \
                redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exit_:
                cl.check_integration(obj, {"tree": "tree", "files": ["a/x.py"]}, False)
        self.assertEqual(exit_.exception.code, 3)
        self.assertEqual(events, ["start first", "finish first", "start second", "finish second"])
        self.assertEqual(output.getvalue(), "FAIL compile A (a) (3 s)\n  | bad\nPASS compile B (b) (4 s)\n")
        run.assert_called_once_with("tree", steps, {}, concurrent=False, on_result=ANY)

    def test_check_integration_runs_repo_step_after_zone_tests_with_integration_env(self):
        obj = team()
        rec = {"tree": "tree", "files": ["a/x.py"]}
        with patch.object(cl, "duplicate_rulings", return_value=[]), \
                patch.object(cl, "reach", return_value=["A", "B"]), \
                patch.object(cl, "compile_steps", return_value=[]), \
                patch.object(cl, "zone_tests", side_effect=[[('tests A', 'run A')], [('tests B', 'run B')]]), \
                patch.object(cl, "repo_integration_steps", return_value=[('integration tests (tests/integration)', 'run repo')], create=True) as repo, \
                patch.object(cl, "repo_test_steps", return_value=[('unit tests (tests/unit)', 'run units')], create=True), \
                patch.object(cl, "team_env", side_effect=lambda t, group: {"CODETEAM_TEST_GROUP": group}), \
                patch.object(cl, "run_steps", return_value=(True, [])) as run:
            self.assertEqual(cl.check_integration(obj, rec, False), ["A", "B"])
        repo.assert_called_once_with("tree", "tests/integration", "land", str(ROOT / "bin" / "zone-tool"))
        self.assertEqual(run.call_args_list, [
            call("tree", [], {"CODETEAM_TEST_GROUP": "integration"}, concurrent=False, on_result=ANY),
            call("tree", [('unit tests (tests/unit)', 'run units')], {"CODETEAM_TEST_GROUP": "unit"}, concurrent=True, on_result=ANY),
            call("tree", [('tests A', 'run A'), ('tests B', 'run B'),
                          ('integration tests (tests/integration)', 'run repo')],
                 {"CODETEAM_TEST_GROUP": "integration"}, concurrent=True, on_result=ANY),
        ])


class RepoIntegration(unittest.TestCase):
    def test_missing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cl.repo_integration_steps(tmp, "tests/integration", "land", "/zt"), [])

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "suite").mkdir()
            self.assertEqual(cl.repo_integration_steps(tmp, "suite", "land", "/zt"), [])

    def test_pytest_file_and_script_both_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "suite"
            folder.mkdir()
            (folder / "test_one.py").touch()
            (folder / "run.sh").touch()
            self.assertEqual(cl.repo_integration_steps(tmp, "suite", "land", "/zt"),
                [("integration tests (suite)", "/zt job submit --class land --wait 0 --key 'repo suite test-group=integration' -- sh -c 'rc=0; python3 -m pytest -q suite || rc=1; sh suite/run.sh || rc=1; exit $rc'")])

    def test_scripts_sorted_chain_and_full_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "suite"
            folder.mkdir()
            (folder / "z.sh").touch()
            (folder / "a.py").touch()
            self.assertEqual(cl.repo_integration_steps(tmp, "suite", "full", "/zt"),
                [("integration tests (suite)", "/zt job submit --class full --wait 0 --key 'repo suite test-group=integration' -- sh -c 'rc=0; python3 suite/a.py || rc=1; sh suite/z.sh || rc=1; exit $rc'")])

    def test_validate_suite_repo_failure_sets_exit_and_validation_environment(self):
        obj = team()
        with patch.object(cl, "compile_steps") as compile_steps, patch.object(cl, "zone_tests", return_value=[]), \
                patch.object(cl, "repo_test_steps", return_value=[("repo", "run")]) as repo, \
                patch.object(cl, "team_env", side_effect=lambda t, group: {"CODETEAM_TEST_GROUP": group}), \
                patch.object(cl, "run_steps", return_value=(False, ["FAIL repo"])) as run:
            with self.assertRaises(SystemExit) as exit_:
                cl.cmd_validate_suite(obj, None)
        self.assertEqual(exit_.exception.code, 1)
        self.assertEqual(run.call_args.args[2], {"CODETEAM_TEST_GROUP": "validation"})
        self.assertEqual(repo.call_args.args[1:4], ("tests/validation", "validation", "full"))
        compile_steps.assert_not_called()


class Sets(unittest.TestCase):
    def test_queue_entry_one_member_preserves_shape(self):
        self.assertEqual(cl.queue_entry("one", "t1", "base", ["B", "A"], "now", [("one", "t1")]),
            {"wos": ["one"], "wo": "one", "tip": "t1", "base": "base", "zones": ["A", "B"],
             "queued": "now", "state": "waiting", "review": "pending"})

    def test_queue_entry_set_shape(self):
        self.assertEqual(cl.queue_entry("one", "t1", "base", ["B", "A"], "now", [("one", "t1"), ("two", "t2")]),
            {"wos": ["one", "two"], "wo": "one", "tip": "t1", "tips": [["one", "t1"], ["two", "t2"]],
             "base": "base", "zones": ["A", "B"], "queued": "now", "state": "waiting", "review": "pending"})

    def test_entry_members_both_shapes(self):
        self.assertEqual(cl.entry_members({"wo": "one", "tip": "t1"}), [("one", "t1")])
        self.assertEqual(cl.entry_members({"tips": [["one", "t1"], ["two", "t2"]]}), [("one", "t1"), ("two", "t2")])

    def test_merge_chain_all_members(self):
        merge = Mock(side_effect=[("m1", []), ("m2", [])])
        self.assertEqual(cl.merge_chain("old", [("one", "t1"), ("two", "t2")], merge),
                         ([("one", "m1"), ("two", "m2")], [], None))
        self.assertEqual(merge.call_args_list, [call("old", "one", "t1"), call("m1", "two", "t2")])

    def test_merge_chain_conflict_stops_at_second(self):
        merge = Mock(side_effect=[("m1", []), (None, ["b/file"])])
        self.assertEqual(cl.merge_chain("old", [("one", "t1"), ("two", "t2"), ("three", "t3")], merge),
                         ([], ["b/file"], "two"))
        self.assertEqual(merge.call_count, 2)

    def test_units_to_rerun_unique_in_member_order(self):
        self.assertEqual(cl.units_to_rerun({"A": ["a"], "B": ["b"]},
            [("B", ["b/x"]), ("A", ["a/x"]), ("B", ["b/y"]), ("A", ["else/x"])]), ["B", "A"])

    def test_land_duplicate_refused(self):
        obj = team()
        with redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as ex:
            cl.cmd_land(obj, SimpleNamespace(wo="one", with_=["one"], untested=False))
        self.assertEqual(ex.exception.code, 5)
        self.assertNotIn("--with is not in branch flow", err.getvalue())

    def test_land_queued_second_member_refused(self):
        obj = team()
        with patch.object(cl, "entry_path", side_effect=lambda t, w: "queued" if w == "two" else None), \
                redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as ex:
            cl.cmd_land(obj, SimpleNamespace(wo="one", with_=["two"], untested=False))
        self.assertEqual(ex.exception.code, 5)
        self.assertIn("two is already queued", err.getvalue())

    def test_land_restores_first_branch_on_check_failure(self):
        obj = team()
        records = {"one": {"wo": "one", "zone": "A", "tree": "tree1", "branch": "wo/A/one"},
                   "two": {"wo": "two", "zone": "B", "tree": "tree2", "branch": "wo/B/two"}}
        obj.wo.side_effect = lambda w: records[w]
        args = SimpleNamespace(wo="one", with_=["two"], untested=False, feature=None, fixes=None, doc_level=None, doc=None)
        with ExitStack() as stack:
            stack.enter_context(patch.object(cl, "entry_path", return_value=None))
            stack.enter_context(patch.object(cl, "check_work_order", side_effect=[["a/x"], ["b/x"]]))
            stack.enter_context(patch.object(cl, "current_units", return_value=True))
            stack.enter_context(patch.object(cl, "out", side_effect=lambda tree, *args: "" if args[0] == "diff" else "tip"))
            git = stack.enter_context(patch.object(cl, "git", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")))
            stack.enter_context(patch.object(cl, "changed_files", return_value=["a/x", "b/x"]))
            stack.enter_context(patch.object(cl, "check_integration", side_effect=SystemExit(3)))
            stack.enter_context(redirect_stderr(io.StringIO()))
            with self.assertRaises(SystemExit) as ex:
                cl.cmd_land(obj, args)
        self.assertEqual(ex.exception.code, 3)
        self.assertTrue(any(c.args[0] == "tree1" and c.args[1] == "checkout" and "wo/A/one" in c.args for c in git.call_args_list))

    def test_recheck_one_after_landing_receives_all_members_once(self):
        obj = team()
        row = {"M": "m2", "wo": "one", "set": ["one", "two"], "overlapping": [], "zones": ["A"]}
        records = {"one": {"wo": "one", "zone": "A", "fixes": ["f1"]},
                   "two": {"wo": "two", "zone": "B", "fixes": ["f2"]}}
        with patch.object(cl, "itest_checkout", return_value=Path("tree")), \
                patch.object(cl, "recheck_steps", return_value=([], [])), \
                patch.object(cl, "team_env", return_value={}), patch.object(cl, "step_results", return_value=[]), \
                patch.object(cl, "landed_rec", side_effect=lambda t, w: records[w]), \
                patch.object(cl, "apply_recheck_findings"), patch.object(cl, "Lock"), \
                patch.object(cl, "read_recheck", return_value=[row]), patch.object(cl, "_mark_recheck_done_unlocked"), \
                patch.object(cl, "after_landing") as after:
            cl.recheck_one(obj, row)
        after.assert_called_once_with(obj, [{"wo": "one", "zone": "A"}, {"wo": "two", "zone": "B"}])


class StageTwoSet(unittest.TestCase):
    def setUp(self):
        self.obj = team()
        self.records = {
            "w1": {"wo": "w1", "zone": "A", "tree": "tree1", "branch": "wo/A/w1"},
            "w2": {"wo": "w2", "zone": "B", "tree": "tree2", "branch": "wo/B/w2"},
        }
        self.obj.wo.side_effect = lambda name: self.records[name]
        self.queue_file = self.obj.dir / "queue" / "20000101-000000-w1.json"
        self.args = SimpleNamespace(wo="w1", with_=["w2"], untested=False)
        self.conflict = False
        self.changed_for_second = False
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(cl, "entry_path", return_value=None))
        stack.enter_context(patch.object(cl, "check_work_order", side_effect=lambda t, r: ["a/x.py"] if r["wo"] == "w1" else ["b/x.py"]))
        self.current = stack.enter_context(patch.object(cl, "current_units", return_value=True))
        self.units = stack.enter_context(patch.object(cl, "test_units"))
        stack.enter_context(patch.object(cl, "changed_files", side_effect=lambda tree, base: ["a/x.py"] if tree == "tree1" else ["b/x.py"]))
        stack.enter_context(patch.object(cl, "check_integration", return_value=["A", "B"]))
        stack.enter_context(patch.object(cl, "reach", return_value=["A", "B"]))
        stack.enter_context(patch.object(cl, "queue_notices"))
        stack.enter_context(patch.object(cl, "now", return_value="now"))
        stack.enter_context(patch.object(cl.time, "strftime", return_value="20000101-000000"))
        stack.enter_context(patch.object(cl, "stage3_record", side_effect=lambda t, r, **kw: {"wo": r["wo"], "state": "land", "reviewers": {}, "seen": {}}))
        stack.enter_context(patch.object(cl, "out", side_effect=self.fake_out))
        self.git = stack.enter_context(patch.object(cl, "git", side_effect=self.fake_git))

    def fake_out(self, tree, *args):
        if args[0] == "rev-parse":
            return "BASE" if tree == self.obj.repo else {"tree1": "T1", "tree2": "T2"}[tree]
        if args == ("diff", "--name-only", "--diff-filter=U"):
            return "b/conflict.py"
        if args == ("diff", "--name-only", "T2", "HEAD") and self.changed_for_second:
            return "b/merged.py"
        return ""

    def fake_git(self, tree, *args, **kwargs):
        failed = self.conflict and args == ("merge", "--no-edit", "T2")
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def test_set_queues_one_entry_with_each_members_tip_and_set(self):
        cl.cmd_land(self.obj, self.args)
        self.assertTrue(self.queue_file.is_file())
        entry = json.loads(self.queue_file.read_text())
        self.assertEqual(entry["wos"], ["w1", "w2"])
        self.assertEqual(entry["tips"], [["w1", "T1"], ["w2", "T2"]])
        self.assertEqual([r["set"] for r in self.records.values()], [["w1", "w2"], ["w1", "w2"]])
        self.assertEqual(entry["review"], "land")

    def test_second_merge_conflict_aborts_restores_branch_and_does_not_queue(self):
        self.conflict = True
        with self.assertRaises(SystemExit) as ex:
            cl.cmd_land(self.obj, self.args)
        self.assertEqual(ex.exception.code, 2)
        # check=False: when git refused to start the merge there is nothing to abort.
        self.assertIn(call("tree1", "merge", "--abort", check=False), self.git.call_args_list)
        tree_calls = [c for c in self.git.call_args_list if c.args[0] == "tree1"]
        self.assertEqual(tree_calls[-1], call("tree1", "checkout", "-q", "wo/A/w1"))
        self.assertFalse(self.queue_file.exists())

    def test_a_set_tests_each_members_zone_once_on_the_merged_tips_in_the_first_tree(self):
        # Never a member alone, so halves that build only together land.
        self.current.return_value = False
        cl.cmd_land(self.obj, self.args)
        self.assertEqual([(c.args[0], c.args[1]["tree"], c.args[2]) for c in self.units.call_args_list],
                         [(self.obj, "tree1", "A"), (self.obj, "tree1", "B")])

    def test_a_set_tests_other_zones_in_the_first_record_itself_never_a_copy_with_their_zone(self):
        # dict(first, zone=zone) once was saved by stage2_steps over the first member's record.
        self.current.return_value = False
        cl.cmd_land(self.obj, self.args)
        self.assertTrue(all(c.args[1] is self.records["w1"] for c in self.units.call_args_list))
        self.assertEqual(self.records["w1"]["zone"], "A")

    def test_a_set_checks_its_merged_files_without_putting_them_in_the_first_record(self):
        with patch.object(cl, "check_integration", return_value=["A", "B"]) as check:
            cl.cmd_land(self.obj, self.args)
        self.assertIs(check.call_args.args[1], self.records["w1"])
        self.assertEqual(check.call_args.kwargs["files"], ["a/x.py"])

    def test_a_set_whose_merged_units_are_current_runs_none(self):
        cl.cmd_land(self.obj, self.args)
        self.units.assert_not_called()


class StoppedLand(unittest.TestCase):
    """A land a live land of the same team holds is refused before any check, and an interrupted concurrent run
    stops its running steps. The two cases that send this process a real SIGTERM or SIGHUP are integration
    tests: tests/integration/land-stopped-by-signal.py."""

    def test_a_land_of_a_member_a_live_land_holds_is_refused_before_any_check(self):
        # The second land once read the live set's merge in the tree; now it never reaches it.
        stages = cl.buildq_dir().parent / "restart" / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        row = stages / "holder.json"
        row.write_text(json.dumps({"stage": "Stage 2", "name": "check of two", "pid": os.getppid(), "started": "t",
                                   "team": str(Path("/team.toml")), "wos": ["two"]}))
        self.addCleanup(row.unlink, missing_ok=True)
        args = SimpleNamespace(wo="one", with_=["two"], untested=False)
        with patch.object(cl, "check_and_queue") as check, redirect_stderr(io.StringIO()) as err, \
                self.assertRaises(SystemExit) as ex:
            cl.cmd_land(team(), args)
        self.assertEqual(ex.exception.code, cl.REFUSED)
        check.assert_not_called()
        self.assertIn("two: a land of it is already running", err.getvalue())

    def test_an_interrupted_concurrent_run_stops_each_running_steps_process_group(self):
        running, ended = Mock(pid=101), Mock(pid=102)
        running.poll.return_value, ended.poll.return_value = None, 0
        with patch.object(cl.os, "killpg") as killpg:
            cl.stop_steps([("a", 0.0, running), ("b", 0.0, ended)])
        killpg.assert_called_once_with(101, cl.signal.SIGTERM)


class LandingSet(unittest.TestCase):
    def setUp(self):
        self.obj = team()
        self.records = {"one": {"wo": "one", "zone": "A", "tree": "tree1", "branch": "b1", "reach": [], "queued": "now"},
                        "two": {"wo": "two", "zone": "B", "tree": "tree2", "branch": "b2", "reach": [], "queued": "now"}}
        self.obj.wo.side_effect = lambda w: self.records[w]
        self.p = MagicMock()
        self.p.read_text.return_value = json.dumps({"wos": ["one", "two"], "wo": "one", "tip": "t1",
            "tips": [["one", "t1"], ["two", "t2"]], "base": "base", "zones": ["A", "B"], "review": "land"})

    def run_entry(self, conflict=False, overlap=False):
        def fake_git(repo, *args, **kwargs):
            if args[0] == "merge-tree":
                if conflict and args[-1] == "t2":
                    return SimpleNamespace(returncode=1, stdout="tree\nb/file\n\nconflict", stderr="")
                return SimpleNamespace(returncode=0, stdout="tree\n", stderr="")
            if args[0] == "commit-tree":
                return SimpleNamespace(returncode=0, stdout="m1\n" if "t1" in args else "m2\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with ExitStack() as stack:
            stack.enter_context(patch.object(cl, "integration_holders", return_value=[]))
            stack.enter_context(patch.object(cl, "out", side_effect=lambda repo, *args: "old" if args[0] == "rev-parse" else "log"))
            git = stack.enter_context(patch.object(cl, "git", side_effect=fake_git))
            move = stack.enter_context(patch.object(cl, "move_landing", return_value=True))
            stack.enter_context(patch.object(cl, "cleanup_landing"))
            stack.enter_context(patch.object(cl, "intervening_landings", return_value=[("prior", ["a/x"])] if overlap else []))
            stack.enter_context(patch.object(cl, "docs_pass"))
            after = stack.enter_context(patch.object(cl, "after_landing"))
            files = stack.enter_context(patch("builtins.open", mock_open()))
            result = cl.land_entry(self.obj, self.p)
        return result, git, move, after, files

    def test_set_moves_once_updates_each_landed_ref_and_reviews_once(self):
        result, git, move, after, _ = self.run_entry()
        self.assertEqual(result, 0)
        move.assert_called_once_with(self.obj, "m2", "old")
        self.assertIn(call(self.obj.repo, "update-ref", "refs/landed/one", "t1"), git.call_args_list)
        self.assertIn(call(self.obj.repo, "update-ref", "refs/landed/two", "t2"), git.call_args_list)
        self.assertEqual(self.records["one"]["landed_commit"], "m1")
        self.assertEqual(self.records["two"]["landed_commit"], "m2")
        after.assert_called_once()
        self.assertEqual([r["wo"] for r in after.call_args.args[1]], ["one", "two"])

    def test_set_overlap_writes_one_recheck_row_for_all(self):
        result, _, _, after, files = self.run_entry(overlap=True)
        self.assertEqual(result, 0)
        rows = [json.loads(c.args[0]) for c in files().write.call_args_list]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["M"], rows[0]["wo"], rows[0].get("set")), ("m2", "one", ["one", "two"]))
        after.assert_not_called()

    def test_set_conflict_bounces_every_member_without_move(self):
        result, _, move, after, _ = self.run_entry(conflict=True)
        self.assertEqual(result, 2)
        move.assert_not_called()
        after.assert_not_called()
        self.assertNotIn("queued", self.records["one"])
        self.assertNotIn("queued", self.records["two"])
        self.p.unlink.assert_called_once()
        self.assertEqual(self.obj.notify.call_count, 2)
        self.assertEqual(self.obj.log.call_args.args[0]["wos"], ["one", "two"])
        self.assertEqual(self.obj.log.call_args.args[0]["result"], "conflict")

    def test_conflict_notice_identifies_responsible_member_only(self):
        result, _, move, _, _ = self.run_entry(conflict=True)
        self.assertEqual(result, 2)
        move.assert_not_called()
        self.assertNotIn("queued", self.records["one"])
        self.assertNotIn("queued", self.records["two"])
        self.p.unlink.assert_called_once()
        notices = {c.args[0]: c.args[2] for c in self.obj.notify.call_args_list if c.args[1] == "NOTE"}
        self.assertEqual(set(notices), {"Coord-A", "Coord-B"})
        self.assertIn("b/file", notices["Coord-B"])
        self.assertIn("resolve", notices["Coord-B"])
        self.assertIn("not merge landing", notices["Coord-B"])
        self.assertIn("promoted", notices["Coord-B"])
        self.assertNotIn("b/file", notices["Coord-A"])
        self.assertNotIn("resolve in", notices["Coord-A"])
        self.assertIn("two", notices["Coord-A"])
        self.assertIn("set", notices["Coord-A"].lower())
        self.assertIn("conflict", notices["Coord-A"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
