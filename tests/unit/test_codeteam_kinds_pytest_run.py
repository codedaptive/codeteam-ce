import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHARE = str((ROOT / "share").resolve())
spec = importlib.util.spec_from_file_location("codeteam_kinds_pytest_run", ROOT / "share" / "codeteam_kinds_pytest_run.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode

CMD = ["py", "-m", "pytest", "-q", "-p", "no:cacheprovider", "pkg"]


def test_plugin_options_go_after_no_cacheprovider_and_before_the_path():
    cmd, _ = module.with_kinds(CMD, {"PYTHONPATH": "/x"}, "integration")
    assert cmd == ["py", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   "-p", "codeteam_kinds_pytest", "--codeteam-kind=integration", "pkg"]


def test_plugin_options_without_a_path_end_the_command():
    cmd, _ = module.with_kinds(["py", "-m", "pytest", "-q", "-p", "no:cacheprovider"], {}, "unit")
    assert cmd == ["py", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   "-p", "codeteam_kinds_pytest", "--codeteam-kind=unit"]


def test_share_goes_before_the_inherited_pythonpath():
    _, env = module.with_kinds(CMD, {"PYTHONPATH": "/x", "HOME": "/h"}, "integration")
    assert env == {"PYTHONPATH": SHARE + os.pathsep + "/x", "HOME": "/h"}


def test_no_inherited_pythonpath_gives_share_only():
    _, env = module.with_kinds(CMD, {"HOME": "/h"}, "integration")
    assert env == {"PYTHONPATH": SHARE, "HOME": "/h"}


def test_an_empty_inherited_pythonpath_gives_share_only():
    _, env = module.with_kinds(CMD, {"PYTHONPATH": ""}, "unit")
    assert env == {"PYTHONPATH": SHARE}


def test_inputs_are_not_changed():
    cmd_in = list(CMD)
    env_in = {"PYTHONPATH": "/x"}
    module.with_kinds(cmd_in, env_in, "integration")
    assert cmd_in == ["py", "-m", "pytest", "-q", "-p", "no:cacheprovider", "pkg"]
    assert env_in == {"PYTHONPATH": "/x"}
