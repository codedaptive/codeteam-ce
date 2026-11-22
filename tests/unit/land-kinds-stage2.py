#!/usr/bin/env python3
"""Stage 2's switch changes unit evidence; integration batches are deferred to landing."""
import contextlib
import importlib.machinery
import importlib.util
import io
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_kinds_stage2", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)


def fixture(on):
    records = {"one": {"wo": "one", "zone": "A", "tree": "tree1", "branch": "branch1"},
               "two": {"wo": "two", "zone": "B", "tree": "tree2", "branch": "branch2"}}
    team = SimpleNamespace(m={"env": {"CODETEAM_KINDS_BY_NAME": "1" if on else "0"}},
                           zones={"A": ["a"], "B": ["b"]}, integration="integration",
                           c=lambda key, default: default, wo=lambda name: records[name], save_wo=Mock())
    return team, records


def drive(on, names, current=None):
    """Stage 2 over the fixture's records: (batches, test_units calls, records, zone_tests' (zone, class) calls).
    current answers current_units(team, tree, zone, files); by default every tree has its record when the switch is
    on and none when it is off."""
    team, records = fixture(on)
    batches, classes = [], []
    def batch(team, rec, steps, group, **kwargs):
        batches.append((kwargs.get("kind", group), steps))
        return True
    def zone_tests(team, tree, zone, cls, **kwargs):
        classes.append((zone, cls))
        return [("unit " + zone, "run " + zone)]
    with contextlib.ExitStack() as stack:
        for name, kwargs in {
            "entry_path": {"return_value": None}, "put_back_set_merge": {}, "carried_check": {"return_value": None},
            "other_member_heads": {"return_value": [], "create": True},
            "check_work_order": {"side_effect": lambda team, rec, *args: ["a/x"] if rec["wo"] == "one" else ["b/x"]},
            "no_build_kind": {"return_value": None},
            "current_units": {"side_effect": current or (lambda team, tree, zone, files=(): on)},
            "unit_folders": {"return_value": ["a"]}, "lane_owns_join": {"return_value": "a"},
            "out": {"return_value": "0123456789abcdef"},
            "git": {"return_value": SimpleNamespace(returncode=0)}, "own_base": {"return_value": "base"},
            "changed_files": {"return_value": ["a/x", "b/x"]}, "reach": {"return_value": ["A", "B"]},
            "duplicate_rulings": {"return_value": []}, "compile_steps": {"return_value": [("compile", "compile cmd")]},
            "repo_test_steps": {"return_value": [("repo unit", "unit cmd")]},
            "zone_steps": {"return_value": [("integration", "integration cmd")]},
            "zone_tests": {"side_effect": zone_tests}, "stage2_steps": {"side_effect": batch},
        }.items():
            stack.enter_context(patch.object(cl, name, **kwargs))
        units = stack.enter_context(patch.object(cl, "test_units", wraps=cl.test_units))
        members = cl.checked_members(team, names)
        cl.merge_checked_base(team, members[0][0], "base", None, test=len(names) == 1)
        for rec, _ in members:
            rec.update(tip="0123456789abcdef", files=["a/x", "b/x"])
        cl.check_combined_members(team, members, "base")
    return batches, units.call_count, records, classes


class StageTwoTests(unittest.TestCase):
    def test_off_lone_regression(self):
        batches, calls, _, _ = drive(False, ["one"])
        self.assertEqual(batches, [("unit", [("unit A", "run A")]),
                                   ("compile", [("compile", "compile cmd")]),
                                   ("unit", [("repo unit", "unit cmd")])])
        self.assertEqual(calls, 1)

    def test_off_set_regression(self):
        batches, calls, _, _ = drive(False, ["one", "two"])
        self.assertEqual(batches, [("unit", [("unit A", "run A")]), ("unit", [("unit B", "run B")]),
                                   ("compile", [("compile", "compile cmd")]),
                                   ("unit", [("repo unit", "unit cmd")])])
        self.assertEqual(calls, 2)

    def test_on_lone_stage2_has_no_units(self):
        batches, calls, _, _ = drive(True, ["one"])
        self.assertEqual(batches, [("compile", [("compile", "compile cmd")])])
        self.assertEqual(calls, 0)

    def test_on_set_stage2_has_no_units(self):
        batches, calls, records, _ = drive(True, ["one", "two"])
        self.assertEqual(batches, [("compile", [("compile", "compile cmd")])])
        self.assertEqual(calls, 0)
        self.assertNotIn("units_on_merge", records["one"])
        self.assertNotIn("units_on_merge", records["two"])

    def test_on_set_member_without_its_own_record_is_unit_tested_on_the_merged_tips(self):
        # A set's WidgetCoreKit member imports VaultKit's new codec from
        # another member, so it can never make a unit record at its own tip. Its units run once on the set's merged
        # tips, with the commands its lead would have run, at the landing class; the member with a record is not run.
        batches, calls, records, classes = drive(True, ["one", "two"],
                                                 lambda team, tree, zone, files=(): zone == "B")
        self.assertEqual(batches, [("unit", [("unit A", "CODETEAM_KINDS_BY_NAME=1 CODETEAM_OWNS=a run A")]),
                                   ("compile", [("compile", "compile cmd")])])
        self.assertEqual(classes, [("A", "land")])
        self.assertEqual(calls, 0)
        self.assertIs(records["one"]["units_on_merge"], True)
        self.assertNotIn("units_on_merge", records["two"])

    def test_on_merged_tips_with_their_record_run_no_units(self):
        # A land run again on the same merged tips (after a later step failed) finds the merged run's record.
        merged = lambda team, tree, zone, files=(): zone == "B" or list(files) == ["a/x", "b/x"]
        batches, calls, records, classes = drive(True, ["one", "two"], merged)
        self.assertEqual(batches, [("compile", [("compile", "compile cmd")])])
        self.assertEqual(classes, [])
        self.assertIs(records["one"]["units_on_merge"], True)

    def test_on_a_member_with_its_record_now_drops_the_last_attempts_mark(self):
        team, records = fixture(True)
        records["one"]["units_on_merge"] = True
        with patch.object(cl, "entry_path", return_value=None), patch.object(cl, "put_back_set_merge"), \
                patch.object(cl, "carried_check", return_value=None), \
                patch.object(cl, "check_work_order", side_effect=[["a/x"], ["b/x"]]), \
                patch.object(cl, "other_member_heads", return_value=[], create=True), \
                patch.object(cl, "no_build_kind", return_value=None), patch.object(cl, "current_units", return_value=True):
            cl.checked_members(team, ["one", "two"])
        self.assertNotIn("units_on_merge", records["one"])

    def test_on_lone_missing_record_refuses_with_evidence(self):
        team, records = fixture(True)
        err = io.StringIO()
        with patch.object(cl, "entry_path", return_value=None), patch.object(cl, "put_back_set_merge"), \
                patch.object(cl, "carried_check", return_value=None), \
                patch.object(cl, "check_work_order", return_value=["a/x"]), \
                patch.object(cl, "no_build_kind", return_value=None), patch.object(cl, "current_units", return_value=False), \
                patch.object(cl, "unit_step_keys", return_value=["key A"]), \
                patch.object(cl, "zone_tests", return_value=[("test", "make test")]), \
                patch.object(cl, "out", return_value="0123456789abcdef"), patch.object(cl, "test_units") as units, \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as exit_:
                cl.checked_members(team, ["one"])
        self.assertEqual(exit_.exception.code, 5)
        for text in ("one", "A", "0123456789", "key A", "make test", "CODETEAM_KINDS_BY_NAME=1", "land again"):
            self.assertIn(text, err.getvalue())
        units.assert_not_called()

    def test_on_each_set_member_is_checked_in_its_own_tree(self):
        team, records = fixture(True)
        with patch.object(cl, "entry_path", return_value=None), patch.object(cl, "put_back_set_merge"), \
                patch.object(cl, "carried_check", return_value=None), \
                patch.object(cl, "check_work_order", side_effect=[["a/x"], ["b/x"]]), \
                patch.object(cl, "other_member_heads", return_value=[], create=True), \
                patch.object(cl, "no_build_kind", return_value=None), \
                patch.object(cl, "current_units", return_value=True) as current, patch.object(cl, "test_units") as units:
            self.assertEqual(cl.checked_members(team, ["one", "two"]), [(records["one"], None), (records["two"], None)])
        self.assertEqual(current.call_args_list, [call(team, Path("tree1"), "A", ["a/x"]),
                                                  call(team, Path("tree2"), "B", ["b/x"])])
        units.assert_not_called()

    def test_on_no_build_is_not_checked(self):
        team, records = fixture(True)
        with patch.object(cl, "entry_path", return_value=None), patch.object(cl, "put_back_set_merge"), \
                patch.object(cl, "carried_check", return_value=None), \
                patch.object(cl, "check_work_order", return_value=["a/doc.md"]), \
                patch.object(cl, "no_build_kind", return_value="docs-only"), \
                patch.object(cl, "current_units") as current, patch.object(cl, "test_units") as units:
            self.assertEqual(cl.checked_members(team, ["one"]), [(records["one"], "docs-only")])
        current.assert_not_called()
        units.assert_not_called()

    def test_on_combined_set_whose_members_have_their_records_checks_no_units(self):
        team, records = fixture(True)
        for record in records.values():
            record["tip"] = "tip"
        with patch.object(cl, "merge_set_tips"), patch.object(cl, "git"), \
                patch.object(cl, "own_base", return_value="base"), patch.object(cl, "changed_files", return_value=["a/x"]), \
                patch.object(cl, "check_integration", return_value=["A"]), patch.object(cl, "reach", return_value=["A"]), \
                patch.object(cl, "current_units", return_value=False) as current, patch.object(cl, "test_units") as units:
            self.assertEqual(cl.check_combined_members(team, [(records["one"], None), (records["two"], None)], "base"),
                             (["A"], ["A"]))
        current.assert_not_called()
        units.assert_not_called()

    def test_on_merge_does_not_retest_changed_zone(self):
        team, records = fixture(True)
        with patch.object(cl, "out", side_effect=["before", "a/new.py"]), \
                patch.object(cl, "git", return_value=SimpleNamespace(returncode=0)), \
                patch.object(cl, "work_order_files", return_value=["a/x"]), patch.object(cl, "test_units") as units:
            cl.merge_checked_base(team, records["one"], "base", None)
        units.assert_not_called()

    def test_key_env_uses_manifest_owns_only_when_on(self):
        for on, owns, expected in [(True, ["a", "b/**"], {"GROUP": "unit", "CODETEAM_OWNS": "a:b/**"}),
                                   (True, [], {"GROUP": "unit", "CODETEAM_OWNS": ""}),
                                   (False, ["a"], {"GROUP": "unit"})]:
            with self.subTest(on=on, owns=owns):
                team, _ = fixture(on)
                team.m["lanes"] = [{"name": "A", "owns": owns}]
                with patch.object(cl, "test_folders", return_value=["a"]), \
                        patch.object(cl, "team_env", return_value={"GROUP": "unit"}), \
                        patch.object(cl.subprocess, "run", return_value=SimpleNamespace(
                            returncode=0, stdout="CODETEAM-UNIT-KEY=key\n")) as make:
                    self.assertEqual(cl.unit_step_keys(team, Path("tree"), "A", ["a/x"]), ["key"])
                self.assertEqual(make.call_args.kwargs["env"], expected)

    def test_recheck_steps_unchanged_on_and_off(self):
        for on in (False, True):
            team, _ = fixture(on)
            with patch.object(cl, "compile_steps", return_value=[("repo gates", "gate"), ("compile", "compile cmd")]), \
                    patch.object(cl, "zone_steps", return_value=[("integration", "integration cmd")]):
                self.assertEqual(cl.recheck_steps(team, Path("tree"), ["A"], ["a/x"]),
                                 ([("compile", "compile cmd")], [("integration", "integration cmd")]))


def make_key(args, **kwargs):
    """The fake make: the unit key it prints names the DIR it was asked for."""
    folder = next(a.removeprefix("DIR=") for a in args if a.startswith("DIR="))
    return SimpleNamespace(returncode=0, stdout=f"CODETEAM-UNIT-KEY=one {folder}\n")


class LooseOwnedTests(unittest.TestCase):
    """A lane that owns test files in none of its test roots (tests/unit/land-*.py)
    proves its units, under the switch, with its root run, which runs every owned test once."""

    def keys(self, on, loose):
        team, _ = fixture(on)
        team.m["lanes"] = [{"name": "A", "owns": ["a", "tests/unit/land-*.py"]}]
        with patch.object(cl, "test_folders", return_value=["a"]), \
                patch.object(cl, "team_env", return_value={"GROUP": "unit"}), \
                patch.object(cl, "unit_plan", return_value="plan"), \
                patch.object(cl, "loose_owned_tests", return_value=loose) as found, \
                patch.object(cl.subprocess, "run", side_effect=make_key):
            return cl.unit_step_keys(team, Path("tree"), "A", ["a/x"]), found

    def test_on_with_loose_tests_the_root_record_is_the_evidence(self):
        keys, found = self.keys(True, ["tests/unit/land-a.py"])
        self.assertEqual(keys, ["one ."])
        self.assertEqual(found.call_args.args, (Path("tree"), ["a"], ["a"], "plan"))

    def test_on_without_loose_tests_the_roots_are_the_evidence(self):
        self.assertEqual(self.keys(True, [])[0], ["one a"])

    def test_off_the_roots_are_the_evidence_and_owns_are_not_read(self):
        keys, found = self.keys(False, ["tests/unit/land-a.py"])
        self.assertEqual(keys, ["one a"])
        found.assert_not_called()

    def test_loose_tests_are_looked_for_outside_every_root_not_only_the_reached_ones(self):
        team, _ = fixture(True)
        calls = []
        def folders(team, tree, zone, group, files=()):
            calls.append(list(files))
            return ["a"] if files else ["a", "a2"]
        with patch.object(cl, "test_folders", side_effect=folders), patch.object(cl, "unit_plan", return_value="p"), \
                patch.object(cl, "loose_owned_tests", return_value=[]) as found:
            self.assertEqual(cl.unit_folders(team, Path("tree"), "A", ["a/x"]), ["a"])
        self.assertEqual(found.call_args.args[2], ["a", "a2"])
        self.assertEqual(calls, [["a/x"], []])

    def test_the_refusal_names_the_root_run_when_it_is_the_evidence(self):
        team, _ = fixture(True)
        with patch.object(cl, "unit_folders", return_value=["."]), patch.object(cl, "zone_tests") as tests:
            self.assertEqual(cl.unit_record_steps(team, Path("tree"), "A", ["a/x"], "dev"),
                             [("tests A (.)", "CODETEAM_KINDS_BY_NAME=1 CODETEAM_OWNS='' "
                                              "make --no-print-directory zone-test-one DIR=. CLASS=dev")])
        tests.assert_not_called()

    def test_the_refusal_names_the_zone_tests_otherwise(self):
        team, _ = fixture(True)
        with patch.object(cl, "unit_folders", return_value=["a"]), \
                patch.object(cl, "zone_tests", return_value=[("tests A (a)", "make a")]) as tests:
            self.assertEqual(cl.unit_record_steps(team, Path("tree"), "A", ["a/x"], "dev"),
                             [("tests A (a)", "CODETEAM_KINDS_BY_NAME=1 CODETEAM_OWNS='' make a")])
        self.assertEqual(tests.call_args.args, (team, Path("tree"), "A", "dev"))

    def test_the_merged_tips_run_takes_the_class_it_is_given(self):
        # The same commands as the refusal's, at the landing's class, so Stage 2 runs them in its own turn.
        team, _ = fixture(True)
        with patch.object(cl, "unit_folders", return_value=["."]):
            self.assertEqual(cl.unit_record_steps(team, Path("tree"), "A", ["a/x"], "land"),
                             [("tests A (.)", "CODETEAM_KINDS_BY_NAME=1 CODETEAM_OWNS='' "
                                              "make --no-print-directory zone-test-one DIR=. CLASS=land")])

    def test_a_lane_with_its_own_test_keeps_its_command(self):
        team, _ = fixture(True)
        team.m["lanes"] = [{"name": "A", "test": "tests/run.sh"}]
        with patch.object(cl, "unit_folders") as folders, \
                patch.object(cl, "zone_tests", return_value=[("lane", "lane cmd")]):
            self.assertEqual(cl.unit_record_steps(team, Path("tree"), "A", [], "dev"),
                             [("lane", "CODETEAM_KINDS_BY_NAME=1 CODETEAM_OWNS='' lane cmd")])
        folders.assert_not_called()

    def test_the_refusal_names_the_owns_the_manifest_gives_now(self):
        # A session keeps the owns it was launched with; the printed command carries the
        # manifest's current ones, quoted for the shell, the same join unit_step_keys asks make for the key with.
        team, _ = fixture(True)
        team.m["lanes"] = [{"name": "A", "owns": ["tests/unit/land-*.py", "zone"]}]
        with patch.object(cl, "unit_folders", return_value=["."]):
            self.assertEqual(cl.unit_record_steps(team, Path("tree"), "A", ["a/x"], "dev"),
                             [("tests A (.)", "CODETEAM_KINDS_BY_NAME=1 CODETEAM_OWNS='tests/unit/land-*.py:zone' "
                                              "make --no-print-directory zone-test-one DIR=. CLASS=dev")])
        self.assertEqual(cl.lane_owns_join(team, "A"), "tests/unit/land-*.py:zone")

    def test_checked_members_refuses_with_the_unit_record_commands(self):
        team, _ = fixture(True)
        err = io.StringIO()
        with patch.object(cl, "entry_path", return_value=None), patch.object(cl, "put_back_set_merge"), \
                patch.object(cl, "carried_check", return_value=None), \
                patch.object(cl, "check_work_order", return_value=["a/x"]), \
                patch.object(cl, "no_build_kind", return_value=None), patch.object(cl, "current_units", return_value=False), \
                patch.object(cl, "unit_step_keys", return_value=["one ."]), \
                patch.object(cl, "unit_record_steps", return_value=[("tests A (.)", "root cmd")]), \
                patch.object(cl, "out", return_value="0123456789abcdef"), patch.object(cl, "test_units"), \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit):
                cl.checked_members(team, ["one"])
        self.assertIn("root cmd", err.getvalue())
        self.assertIn("'one .'", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
