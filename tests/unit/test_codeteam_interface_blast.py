import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_interface_blast import interface_blast


def test_command_and_timeout():
    run = Mock(return_value=SimpleNamespace(stdout='{"seeds": []}', stderr=""))
    interface_blast("cg", "/tree", "base123", 42, run=run)
    run.assert_called_once_with(["cg", "blast", "-b", "base123", "-f", "json", "-p", "/tree"], 42)


def test_good_answer_is_parsed():
    run = Mock(return_value=SimpleNamespace(stdout='{"seeds": [{"name": "own"}]}', stderr=""))
    assert interface_blast("cg", "/tree", "base", 42, run=run) == ({"seeds": [{"name": "own"}]}, None)


def test_timeout():
    run = Mock(side_effect=subprocess.TimeoutExpired("cg", 42))
    assert interface_blast("cg", "/tree", "base", 42, run=run) == ({}, "codegraph blast timed out")


def test_no_answer_uses_stderr():
    run = Mock(return_value=SimpleNamespace(stdout="bad json", stderr="  no index  \n"))
    assert interface_blast("cg", "/tree", "base", 42, run=run) == (
        {}, "codegraph blast gave no answer (no index?): no index")


def test_no_answer_falls_back_to_stdout():
    run = Mock(return_value=SimpleNamespace(stdout="  not json \n", stderr=""))
    assert interface_blast("cg", "/tree", "base", 42, run=run) == (
        {}, "codegraph blast gave no answer (no index?): not json")


def test_no_answer_uses_last_200_characters():
    run = Mock(return_value=SimpleNamespace(stdout="invalid", stderr="discard" + "x" * 200))
    assert interface_blast("cg", "/tree", "base", 42, run=run) == (
        {}, "codegraph blast gave no answer (no index?): " + "x" * 200)
