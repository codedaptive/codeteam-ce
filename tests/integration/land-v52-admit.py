#!/usr/bin/env -S python3 -u
"""Stage admission and holder contracts: integration tests, because they write real admission records
beside a scratch queue and check real pids (the test's own, its parent's, and a dead one)."""
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
loader = importlib.machinery.SourceFileLoader("cl_admit", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)

# These isolated stage fixtures represent teams that have already moved over.
cl.v54_unmoved = Mock(return_value=False)


def holder_row(stages, pid, team_key, wos, name="hold"):
    stages.mkdir(parents=True, exist_ok=True)
    (stages / f"{name}.json").write_text(json.dumps({"stage": "Stage 2", "name": f"check of {', '.join(wos)}",
                                                     "pid": pid, "started": "06:10", "team": team_key, "wos": wos}))


def marker(qdir):
    p = qdir.parent / "restart" / "buildq.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"requested": "now", "requested_ts": 1, "tip": "0123456789abcdef", "files": []}))
    return p


def test_stage_admission_creates_and_removes_record():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        with cl.stage_admit("Stage 2", "check of a", qdir=qdir):
            files = list((qdir.parent / "restart" / "stages").glob("*.json"))
            assert len(files) == 1
            row = json.loads(files[0].read_text())
            assert row["stage"] == "Stage 2" and row["name"] == "check of a" and row["pid"] == os.getpid() and row["started"]
        assert not files[0].exists()


def test_stage_admission_refuses_a_work_order_a_live_land_of_the_team_holds():
    # a second land of w2, the --with member of a live land mid Stage 2, read the set's merge
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


def test_stage_admission_admits_while_restart_pending():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        marker(qdir)
        admitted = False
        try:
            with cl.stage_admit("Stage 2", "check of a", qdir=qdir):
                admitted = True
                records = list((qdir.parent / "restart" / "stages").glob("*.json"))
                assert len(records) == 1 and json.loads(records[0].read_text())["pid"] == os.getpid()
        except Exception as exc:
            assert False, f"admission raised {type(exc).__name__}"
        assert admitted, "stage was not admitted"


def test_stage_admission_removes_dead_and_keeps_live_records():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / "queue"
        stages = qdir.parent / "restart" / "stages"
        dead_pid = 99999999
        assert not cl.stage_alive(dead_pid)
        holder_row(stages, dead_pid, "/t.toml", ["dead"], "dead")
        holder_row(stages, os.getpid(), "/t.toml", ["live"], "live")
        with cl.stage_admit("Stage 2", "check of a", qdir=qdir):
            assert not (stages / "dead.json").exists()
            assert (stages / "live.json").exists()


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
