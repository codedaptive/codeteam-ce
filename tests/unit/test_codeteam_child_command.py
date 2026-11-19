"""share/codeteam_child_command.py alone (D526): the children's environment keeps the six named CODETEAM_ variables
and drops the other CODETEAM_*, HERDR_* and make's variables; the pytest command is the plain one unless the run
picks kinds by name, when with_kinds (a fake here) makes both. cmd_test_one with it:
tests/unit/test_zone_tool_rit_selector.py and test_zone_tool_kinds.py.
"""
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
spec = importlib.util.spec_from_file_location("codeteam_child_command", ROOT / "share" / "codeteam_child_command.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode

KEPT = {"CODETEAM_HOME": "/ct", "CODETEAM_BUILD_JOBS": "4", "CODETEAM_BUILDQ_TICKET": "t1", "CODETEAM_LANDING": "1",
        "CODETEAM_TEST_GROUP": "integration", "CODETEAM_RIT_SELECTOR": "rit_", "HOME": "/h", "PATH": "/bin"}
DROPPED = {"CODETEAM_MANIFEST": "/live/team.toml", "CODETEAM_OWNS": "a", "HERDR_PANE": "p", "MAKEFLAGS": "-j",
           "MFLAGS": "-s", "MAKELEVEL": "1", "MAKEOVERRIDES": "DIR=x", "DIR": "x"}
PLAIN = ["py3", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


def test_children_keep_the_named_variables_and_drop_team_herdr_and_make_ones(capsys):
    environ = {**KEPT, **DROPPED}
    pytest_cmd, env = module.child_command(environ, "py3", "unit", False)
    assert env == KEPT
    assert pytest_cmd == PLAIN
    assert capsys.readouterr().out == ""
    assert environ == {**KEPT, **DROPPED}


def test_kinds_by_name_says_so_and_returns_what_with_kinds_makes_of_the_plain_command(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(module, "with_kinds",
                        lambda cmd, env, group: calls.append((list(cmd), dict(env), group)) or (["k"], {"K": "1"}))
    assert module.child_command({**KEPT, **DROPPED}, "py3", "integration", True) == (["k"], {"K": "1"})
    assert calls == [(PLAIN, KEPT, "integration")]
    assert capsys.readouterr().out == ("test-one: kinds by name (CODETEAM_KINDS_BY_NAME=1): this integration run runs "
                                       "only tests named integration; an unnamed test is a ZUT, unit run only\n")
