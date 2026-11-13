#!/usr/bin/env -S python3 -u
"""Stages 6 and 7 treat a --with set's landing as one step: Stage 4 merges the members one by one and moves landing
once, to the last, so the commits before it are never validated or promoted (a three-member
set once landed as d5e8bf8a9b, e2016f811f, db0e5c3f12; Stage 6 passed at e2016f811f, the middle one, and Stage 7
promoted a package's changed API without the app's caller change). Git is faked; records live in a temp folder."""
import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_set_boundary", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

SET = ["corpus", "core", "app"]


def team_at(root):
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{root / "repo"}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n[land]\nseed_index = false\n')
    team = cl.Team(manifest)
    team.notify = Mock()
    return team


def landed(team, *rows):
    with open(team.dir / "landed.log", "a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def acme_rows(team, named=True):
    """The case: one lone landing, the three-member set, a lone landing after it, and a promote row."""
    def row(wo, commit):
        return {"wos": [wo], "hash": commit, **({"set": SET} if named and wo in SET else {})}
    landed(team, row("before", "f47"), row("corpus", "d5e"), row("core", "e20"), row("app", "db0"),
           row("tooling", "d15"), {"promote": "f47", "to": "develop"})


def test_a_sets_commits_before_its_last_are_inner():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        acme_rows(team)
        assert cl.set_inner_commits(team) == {"d5e", "e20"}


def test_rows_from_before_d368_are_read_from_the_landed_records():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        acme_rows(team, named=False)
        for wo in SET:
            (team.dir / "wo" / f"{wo}.landed.json").write_text(json.dumps({"wo": wo, "set": SET}))
        (team.dir / "wo" / "before.landed.json").write_text(json.dumps({"wo": "before", "set": ["before"]}))
        assert cl.set_inner_commits(team) == {"d5e", "e20"}


def test_stage6_never_stops_inside_a_set_while_its_recheck_is_pending():
    # First-parent order, newest first; the set's recheck (at its last commit) is pending, so db0 and d15 wait.
    commits = ["d15", "db0", "e20", "d5e", "f47"]
    after = {"db0": {"db0", "d15"}}
    is_ancestor = lambda a, b: b in after.get(a, {a})                 # noqa: E731
    assert cl.rechecked_commit(commits, ["db0"], None, is_ancestor) == "e20"          # what promoted e2016f811f
    assert cl.rechecked_commit(commits, ["db0"], None, is_ancestor, {"d5e", "e20"}) == "f47"
    assert cl.rechecked_commit(commits, [], None, is_ancestor, {"d5e", "e20"}) == "d15"


def test_stage6_target_reads_the_sets_from_landed_log():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        acme_rows(team)
        (team.dir / "recheck.jsonl").write_text(json.dumps({"M": "db0", "wo": "corpus", "set": SET}) + "\n")
        after = {"db0": {"db0", "d15"}}
        with patch.object(cl, "out", return_value="d15\ndb0\ne20\nd5e\nf47\n"), \
                patch.object(cl, "ancestry", return_value=lambda a, b: b in after.get(a, {a})):
            assert cl.stage6_target(team) == "f47"


def test_stage7_never_promotes_inside_a_set():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        acme_rows(team)
        rows = [{"commit": c, "result": "pass", "tests": [{"name": "suite", "result": "pass"}],
                 "time": "2026-11-12T15:00:00-06:00"} for c in ("f47", "e20")]
        with patch.object(cl, "validation_rows", return_value=rows), patch.object(cl, "move_tip", return_value=None), \
                patch.object(cl, "ancestry", return_value=lambda a, b: True), \
                patch.object(cl, "landed_hashes", return_value={}):
            assert cl.promotion_target(team) == "f47"
            try:
                cl.check_promotion(team, "e20")
            except cl.PromotionRefused as ex:
                assert "inside a --with set" in str(ex), ex
            else:
                raise AssertionError("promoted the middle of a set")


def test_a_sets_landed_rows_name_the_set():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        recs = {}
        for wo in ("w1", "w2"):
            recs[wo] = {"wo": wo, "zone": "A", "tip": wo.upper(), "base": "B", "tree": str(team.root / wo),
                        "branch": f"wo/A/{wo}"}
            team.save_wo(recs[wo])
        entry = {"wo": "w1", "tips": [["w1", "W1"], ["w2", "W2"]], "base": "B", "zones": ["A"]}
        with patch.object(cl, "git"), patch.object(cl, "cleanup_landing"):
            rows = cl.record_landing_members(team, entry, "OLD", recs, [("w1", "M1"), ("w2", "M2")], False)
        assert [row["set"] for row in rows] == [["w1", "w2"], ["w1", "w2"]]
        assert cl.set_inner_commits(team) == {"M1"}


def test_a_lone_landing_row_names_no_set():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        rec = {"wo": "w", "zone": "A", "tip": "T", "base": "B", "tree": str(team.root / "w"), "branch": "wo/A/w"}
        team.save_wo(rec)
        with patch.object(cl, "git"), patch.object(cl, "cleanup_landing"):
            rows = cl.record_landing_members(team, {"wo": "w", "tip": "T", "base": "B", "zones": ["A"]}, "OLD",
                                             {"w": rec}, [("w", "M")], False)
        assert "set" not in rows[0]


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:          # report every case, then fail once
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
