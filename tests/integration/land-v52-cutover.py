#!/usr/bin/env -S python3 -u
"""Legacy review isolation and current landing parser contracts. Integration tests: reviewed and
complete_recheck take the real Lock, and a refused land takes the real stage-admission lock in a temp queue folder.
The unit tests are in tests/unit/land-v52-cutover.py."""
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

# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

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


def rec(wo):
    return {"wo": wo, "zone": "A", "landed_commit": "cut", "landed_base": "base", "landed_at": "2026-01-01"}


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
