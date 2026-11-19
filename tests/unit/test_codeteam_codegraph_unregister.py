import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import codeteam_codegraph_unregister as m


def test_runs_project_remove_with_the_path_as_a_string():
    with mock.patch.object(m.subprocess, "run") as run:
        m.codegraph_unregister("/x/codegraph", Path("/t/wo/A/w1"))
    assert run.call_count == 1
    assert run.call_args.args[0] == ["/x/codegraph", "project", "remove", "/t/wo/A/w1"]


def test_passes_a_timeout():
    with mock.patch.object(m.subprocess, "run") as run:
        m.codegraph_unregister("codegraph", Path("/t"))
    assert run.call_args.kwargs.get("timeout") is not None


@pytest.mark.parametrize("error", [OSError("no such file"), subprocess.TimeoutExpired(["codegraph"], 60)])
def test_a_raised_error_is_ignored(error):
    with mock.patch.object(m.subprocess, "run", side_effect=error):
        assert m.codegraph_unregister("codegraph", Path("/t")) is None


def test_a_nonzero_exit_is_ignored():
    def failing_run(argv, **kw):
        # Behaves as the real run does on exit 1: raises only when the caller asked it to check.
        if kw.get("check"):
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 1, b"", b"boom")

    with mock.patch.object(m.subprocess, "run", side_effect=failing_run):
        assert m.codegraph_unregister("codegraph", Path("/t")) is None
