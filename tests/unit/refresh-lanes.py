#!/usr/bin/env -S python3 -u
"""The promote-time lane refresh selects manifests and reports failures."""
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
from codeteam_refresh_lanes import refresh_lanes  # noqa: E402


def fixture(tmp):
    repo = Path(tmp) / "repo"
    return repo, repo / "teams" / "sample.toml", repo / "bin" / "codeteam"


def test_changed_manifest_runs_with_command_options():
    with tempfile.TemporaryDirectory() as tmp:
        repo, manifest, codeteam = fixture(tmp)
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        assert refresh_lanes(repo, ["teams/sample.toml"], [manifest], codeteam, run) == []
        assert run.call_args_list == [call([str(codeteam), "sync-lanes", str(manifest)],
                                           capture_output=True, text=True, timeout=60)]


def test_unchanged_manifest_is_not_run():
    with tempfile.TemporaryDirectory() as tmp:
        repo, manifest, codeteam = fixture(tmp)
        run = Mock()
        assert refresh_lanes(repo, ["teams/other.toml"], [manifest], codeteam, run) == []
        run.assert_not_called()


def test_outside_manifest_is_not_run():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _, codeteam = fixture(tmp)
        run = Mock()
        assert refresh_lanes(repo, ["../outside.toml"], [Path(tmp) / "outside.toml"], codeteam, run) == []
        run.assert_not_called()


def test_duplicate_resolved_manifest_runs_once():
    with tempfile.TemporaryDirectory() as tmp:
        repo, manifest, codeteam = fixture(tmp)
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        alias = repo / "teams" / ".." / "teams" / "sample.toml"
        assert refresh_lanes(repo, ["teams/sample.toml"], [manifest, alias], codeteam, run) == []
        assert run.call_count == 1


def test_nonzero_return_reports_manifest_and_output_tail():
    with tempfile.TemporaryDirectory() as tmp:
        repo, manifest, codeteam = fixture(tmp)
        run = Mock(return_value=SimpleNamespace(returncode=1, stdout="stdout-tail", stderr="stderr-tail"))
        messages = refresh_lanes(repo, ["teams/sample.toml"], [manifest], codeteam, run)
        assert len(messages) == 1 and str(manifest) in messages[0]
        assert "stderr-tail" in messages[0] or "stdout-tail" in messages[0]


def test_oserror_reports_manifest_without_raising():
    with tempfile.TemporaryDirectory() as tmp:
        repo, manifest, codeteam = fixture(tmp)
        run = Mock(side_effect=OSError("cannot start"))
        messages = refresh_lanes(repo, ["teams/sample.toml"], [manifest], codeteam, run)
        assert len(messages) == 1 and str(manifest) in messages[0] and "cannot start" in messages[0]


def test_timeout_reports_manifest_without_raising():
    with tempfile.TemporaryDirectory() as tmp:
        repo, manifest, codeteam = fixture(tmp)
        run = Mock(side_effect=subprocess.TimeoutExpired("codeteam", 60))
        messages = refresh_lanes(repo, ["teams/sample.toml"], [manifest], codeteam, run)
        assert len(messages) == 1 and str(manifest) in messages[0]


def test_successes_return_no_messages():
    with tempfile.TemporaryDirectory() as tmp:
        repo, manifest, codeteam = fixture(tmp)
        other = repo / "teams" / "other.toml"
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        assert refresh_lanes(repo, ["teams/sample.toml", "teams/other.toml"],
                             [manifest, other], codeteam, run) == []
        assert run.call_count == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError:
                print(f"FAIL {name}")
                raise
            print(f"PASS {name}")
    print("all passed")
