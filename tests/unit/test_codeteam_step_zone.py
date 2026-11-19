import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_step_zone import step_zone


def is_test_step(name):
    return name.startswith(("tests ", "rits "))


def test_compile_step_names_its_zone():
    assert step_zone("compile Core (src/core)", is_test_step, lambda name: "never") == "Core"


def test_test_step_goes_to_step_owner():
    assert step_zone("tests B (src/b)", is_test_step, lambda name: "owner of " + name) == "owner of tests B (src/b)"


def test_other_steps_have_no_zone():
    assert step_zone("type check", is_test_step, lambda name: "never") is None
    assert step_zone("compile", is_test_step, lambda name: "never") is None
    assert step_zone("repo gates", is_test_step, lambda name: "never") is None
