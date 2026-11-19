import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_process_cwds import process_cwds


def lsof(stdout, returncode=0):
    return patch.object(subprocess, "run", return_value=SimpleNamespace(stdout=stdout, stderr="", returncode=returncode))


def test_lsof_missing_gives_none():
    with patch.object(subprocess, "run", side_effect=FileNotFoundError("lsof")):
        assert process_cwds() is None


def test_empty_output_gives_none():
    with lsof(""):
        assert process_cwds() is None


def test_name_lines_are_read_even_when_lsof_exits_1():
    with lsof("p12\nn/a\np13\nn/b c\n", returncode=1) as run:
        assert process_cwds() == ["/a", "/b c"]
    assert run.call_args.args[0] == ["lsof", "-a", "-d", "cwd", "-Fn"]


def test_output_without_name_lines_gives_none():
    with lsof("p12\nfcwd\np13\n"):
        assert process_cwds() is None
