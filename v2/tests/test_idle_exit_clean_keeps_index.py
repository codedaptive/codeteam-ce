"""The idle-exit clean removes build output without discarding the lane's index."""
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.clean_idle_lane import clean_idle_lane  # noqa: E402
from conftest import integration_module  # noqa: E402

pytestmark = integration_module


def test_idle_exit_clean_finishes_with_index_and_no_build_output(tmp_path, monkeypatch):
    tree = tmp_path / "lane"
    tree.mkdir()
    subprocess.run(["git", "init", "-q", str(tree)], check=True)
    subprocess.run(
        ["git", "-C", str(tree), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "-c", "core.hooksPath=/dev/null", "commit", "-q", "--allow-empty", "-m", "initial"],
        check=True,
    )
    index = tree / ".codegraph" / "index"
    index.parent.mkdir()
    index.write_text("standing lane index\n")
    target = tree / "target"
    target.mkdir()
    (target / "out").write_text("build output\n")
    queue = tmp_path / "queue"
    queue.mkdir()
    calls = tmp_path / "codegraph-calls"
    stub = tmp_path / "codegraph"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CG_CALLS"\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CODETEAM_QUEUE_DIR", str(queue))
    monkeypatch.setenv("CODETEAM_CODEGRAPH", str(stub))
    monkeypatch.setenv("CG_CALLS", str(calls))
    for name in ("MAKEFILES", "MAKEFLAGS", "ZONE_MK_LOADED", "ZONE_ROOT", "CLEAN_DIRS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("codeteam2.clean_idle_lane.CT_HOME", Path(__file__).resolve().parents[2])
    monkeypatch.setattr("codeteam2.clean_idle_lane.v1._zone_folder_lane", lambda team, rec: False)
    monkeypatch.setattr("codeteam2.clean_idle_lane.v1.lane_wt", lambda team, key, rec: tree)
    team = SimpleNamespace(t=object(), team_json=lambda: {"lanes": {"alpha": {}}})
    session = SimpleNamespace(key="alpha", kind="lane", display="Coord-alpha")
    logs = []

    clean_idle_lane(team, session, logs.append)
    deadline = time.monotonic() + 20
    finished = False
    while time.monotonic() < deadline:
        if not index.exists():
            break
        if not target.exists():
            # make and its recipe retain the tree as cwd until the detached clean finishes.
            processes = subprocess.run(["lsof", "-a", "-d", "cwd", "-t", str(tree)],
                                       capture_output=True, text=True)
            assert processes.returncode in (0, 1), processes.stderr
            if not processes.stdout.strip():
                finished = True
                break
        time.sleep(0.05)

    assert not target.exists(), logs
    assert index.exists(), logs
    assert finished, logs
    assert index.read_text() == "standing lane index\n"
    assert not calls.exists(), calls.read_text() if calls.exists() else ""
