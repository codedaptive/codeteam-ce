#!/usr/bin/env -S python3 -u
"""Legacy review isolation and current landing parser contracts."""
import contextlib
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

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_cutover", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

CUT_TIME = "2026-11-10T12:00:00-06:00"
VERDICT = {"verdict": "land", "reason": "old reason", "time": "old time", "base": "b", "tip": "t"}


def make_team(root):
    repo = root / "repo"
    repo.mkdir()
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{repo}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n'
                        '[[assistants]]\nname = "Perkins"\n'
                        '[[assistants]]\nname = "Nagatha"\n'
                        '[land]\norchestrator = "Skippy"\n')
    team = cl.Team(str(manifest))
    team.notify = Mock()
    return team


def cutover(team):
    (team.dir / "reviews" / "cutover.json").write_text(json.dumps({"commit": "cut", "time": CUT_TIME}))


def save_review(team, wo, state="pending"):
    row = {"stage": 3, "wo": wo, "zone": "A", "feature": wo, "landed_commit": "cut", "base": "base",
           "landed_at": "2026-01-02", "handed": "2026-01-02", "seq": 1, "state": state,
           "by": None, "time": None, "findings": []}
    (team.dir / "reviews" / f"{wo}.json").write_text(json.dumps(row))
    return row


def review(team, wo):
    return json.loads((team.dir / "reviews" / f"{wo}.json").read_text())


def rec(wo):
    return {"wo": wo, "zone": "A", "landed_commit": "cut", "landed_base": "base", "landed_at": "2026-01-01"}


def fake_git(*args, **kwargs):
    return SimpleNamespace(returncode=0 if args[-2:] == ("cut", "cut") else 1, stdout="", stderr="")


def rows_file(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def run_reviewed(team, name):
    cl.main([str(team.manifest), "reviewed", name])


def assert_refused(team, name):
    with contextlib.redirect_stderr(io.StringIO()) as err:
        try:
            run_reviewed(team, name)
        except SystemExit as exc:
            assert exc.code != 0, "refusal exited successfully"
        except KeyError as exc:
            raise AssertionError(f"{name} raised {exc!r} instead of refusing Stage 3 review") from exc
        else:
            raise AssertionError(f"{name} was accepted without Stage 3 eligibility")
    assert name in err.getvalue() and "Stage 3" in err.getvalue(), f"unexpected refusal: {err.getvalue()!r}"





def test_review_records_ignore_v51_verdict():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cutover(team)
        (team.dir / "reviews" / "old-verdict.json").write_text(json.dumps(VERDICT))
        expected = save_review(team, "w")
        try:
            result = cl.review_records(team)
        except KeyError as exc:
            raise AssertionError(f"v5.1 verdict was treated as a Stage 5 record: {exc}") from exc
        assert result == {"w": expected}, f"unexpected records: {result!r}"











def test_reviewed_refuses_v51_verdict_without_round():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        cutover(team)
        path = team.dir / "reviews" / "w.json"
        path.write_text(json.dumps(VERDICT))
        original = path.read_text()
        with patch.object(cl, "Team", return_value=team), patch.dict(os.environ, {"CODETEAM_SESSION": "Kong"}), \
                patch.object(cl, "out", return_value="cut"):
            assert_refused(team, "w")
        assert path.read_text() == original, "refused verdict was modified"














def test_complete_recheck_marks_done_without_review_marker():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        row = {"wo": "w", "set": ["w"]}
        rows_file(team.dir / "recheck.jsonl", [row])
        with patch.object(cl, "after_landing"), patch.object(cl, "landed_rec", return_value=rec("w")):
            cl.complete_recheck(team, row, "finished")
        result = json.loads((team.dir / "recheck.jsonl").read_text())
        assert result.get("done") == "finished" and "stage5" not in result, f"wrong row: {result!r}"


def test_mark_recheck_done_default_has_no_stage5_key():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rows_file(team.dir / "recheck.jsonl", [{"wo": "w"}])
        cl._mark_recheck_done_unlocked(team, 0, "finished")
        result = json.loads((team.dir / "recheck.jsonl").read_text())
        assert result == {"wo": "w", "done": "finished"}














def feature_rounds():
    return [{"n": 1, "time": "2026-11-10T09:00:00-06:00", "wos": ["one"], "reviewed": {}},
            {"n": 2, "time": "2026-11-10T11:00:00-06:00", "wos": ["two", "three"], "reviewed": {}},
            {"n": 3, "time": "2026-11-10T13:00:00-06:00", "wos": ["four"], "reviewed": {}}]














def test_land_with_one_option_adds_all_members():
    with patch.object(cl, "Team", return_value=object()), patch.object(cl, "cmd_land") as land:
        cl.main(["m", "land", "a", "--with", "b", "c"])
    assert land.call_args.args[1].with_ == ["b", "c"]


def test_land_repeated_with_adds_members():
    with patch.object(cl, "Team", return_value=object()), patch.object(cl, "cmd_land") as land:
        cl.main(["m", "land", "a", "--with", "b", "--with", "c"])
    assert land.call_args.args[1].with_ == ["b", "c"], f"lost members: {land.call_args.args[1].with_!r}"


def test_land_without_with_has_no_members():
    with patch.object(cl, "Team", return_value=object()), patch.object(cl, "cmd_land") as land:
        cl.main(["m", "land", "a"])
    assert not land.call_args.args[1].with_


def test_land_duplicate_repeated_with_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        with patch.object(cl, "Team", return_value=team), patch.object(cl, "git", side_effect=AssertionError("real git forbidden")), \
                patch.object(cl, "v54_unmoved", return_value=False), contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                cl.main(["m", "land", "a", "--with", "b", "--with", "b"])
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("duplicate work order was accepted")
        assert "more than once" in err.getvalue(), f"wrong refusal: {err.getvalue()!r}"


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
