#!/usr/bin/env -S python3 -u
"""Legacy review isolation and current landing parser contracts. The unit tests (rule 11): review records and
the recheck mark on a temp folder's records, and land's --with parsing with cmd_land faked. The tests through the
real Lock (reviewed, complete_recheck) and the real stage-admission lock (a refused land) are in
tests/integration/land-v52-cutover.py."""
import importlib.machinery
import importlib.util
import json
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


def rows_file(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))





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


def test_mark_recheck_done_default_has_no_stage5_key():
    with tempfile.TemporaryDirectory() as tmp:
        team = make_team(Path(tmp))
        rows_file(team.dir / "recheck.jsonl", [{"wo": "w"}])
        cl._mark_recheck_done_unlocked(team, 0, "finished")
        result = json.loads((team.dir / "recheck.jsonl").read_text())
        assert result == {"wo": "w", "done": "finished"}














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
