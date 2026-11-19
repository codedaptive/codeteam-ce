"""share/claude-hooks/shell_loop.py and shell-loop-guard.py's decide (2026-11-16): a Bash command holding a for, while or until loop is refused with rule 6's reason; a plain command, a
pipeline, `cd x && make` and a quoted `for` go through, and so does input the hook cannot read. Unit: both are
loaded from their files and called directly, decide with a fake has_loop; nothing runs a shell."""
import importlib.machinery
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / "share" / "claude-hooks"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
    return module


has_loop = load("shell_loop_under_test", HOOKS / "shell_loop.py").has_loop
decide = load("shell_loop_guard_under_test", HOOKS / "shell-loop-guard.py").decide


@pytest.mark.parametrize("cmd", [
    "for f in *.py; do wc -l $f; done",
    "while read l; do echo $l; done < list.txt",
    "until make; do sleep 1; done",
    "cd src && for f in a b; do echo $f; done",
    "ls | while read f; do echo $f; done",
    "echo start\nfor f in a b\ndo echo $f\ndone",
    "x=$(for f in a b; do echo $f; done)",
    "if true; then for f in a; do :; done; fi",
    "cat <<EOF | while read l; do echo $l; done\nbody\nEOF",
    "cd x && \\\nfor f in a; do :; done",
    "( until false; do :; done )",
    # A substitution inside double quotes still runs (other-checkout Kong).
    'echo "$(for f in a; do :; done)"',
    'echo "`while true; do :; done`"',
    'echo "x $(echo "$(until false; do :; done)")"',
    "{ for f in a; do :; done; }",
    "time for f in a; do :; done",
])
def test_a_loop_is_found(cmd):
    assert has_loop(cmd) is True


@pytest.mark.parametrize("cmd", [
    "ls -la",
    "git log --oneline | head -5",
    "cd x && make",
    "grep -n 'for i in' notes.txt",
    'git commit -m "for x in y; do z; done"',
    '"for" x',
    "\\for x",
    "echo for while until",
    "make test-for",
    "rg -n foo src  # loop for each file later",
    "cat <<'EOF' > notes.md\nfor each file\nwhile it runs\nEOF",
    "bash -c 'for f in a; do :; done'",
    "echo hi! for",
    "",
    # A keyword word that is an argument starts no command (other-checkout Kong).
    "echo do for x",
    "echo then for x",
    "echo time for",
    "git log --grep '{' for",
    'echo "$(echo for)"',
    "X=1 for",
])
def test_no_loop_is_found(cmd):
    assert has_loop(cmd) is False


def call(command, tool="Bash"):
    return json.dumps({"tool_name": tool, "tool_input": {"command": command}})


@pytest.fixture
def fake_shell_loop(monkeypatch):
    """shell_loop.py replaced by a fake module, so decide's tests reach no code outside shell-loop-guard.py (rule 11);
    the real join runs in tests/integration/test_shell_loop_guard_script.py. decide
    imports has_loop when it is called, so the fake in sys.modules is the one it gets. The fake answers with
    `answer`, raises it when it is an exception, and records each command it is asked about. The path entry and the
    bytecode flag decide sets are put back after each test."""
    fake = types.ModuleType("shell_loop")
    fake.answer, fake.asked = False, []

    def has_loop(command):
        fake.asked.append(command)
        if isinstance(fake.answer, Exception):
            raise fake.answer
        return fake.answer

    fake.has_loop = has_loop
    monkeypatch.setitem(sys.modules, "shell_loop", fake)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    return fake


def test_a_loop_is_refused_with_rule_6(fake_shell_loop):
    fake_shell_loop.answer = True
    out = json.loads(decide(call("for f in a b; do echo $f; done")))["hookSpecificOutput"]
    assert out == {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                   "permissionDecisionReason": "Rule 6: one plain command per shell call; use the Grep and Glob tools "
                                               "for searches."}
    assert fake_shell_loop.asked == ["for f in a b; do echo $f; done"]


def test_a_command_with_no_loop_goes_through_and_nothing_is_approved(fake_shell_loop):
    fake_shell_loop.answer = False
    assert decide(call("cd x && make")) == ""
    assert fake_shell_loop.asked == ["cd x && make"]


@pytest.mark.parametrize("raw", [
    call("for f in a; do :; done", tool="Read"),          # not a Bash call
    "not json", "", "[]", json.dumps({"tool_name": "Bash"}), json.dumps({"tool_name": "Bash", "tool_input": {"command": 7}}),
])
def test_input_without_a_bash_command_goes_through_unasked(fake_shell_loop, raw):
    fake_shell_loop.answer = True          # every command a loop: only a Bash command string can be refused
    assert decide(raw) == ""
    assert fake_shell_loop.asked == []


def test_a_fault_in_has_loop_lets_the_call_through(fake_shell_loop):
    fake_shell_loop.answer = RuntimeError("tokenizer fault")
    assert decide(call("for f in a; do :; done")) == ""
    assert fake_shell_loop.asked == ["for f in a; do :; done"]
