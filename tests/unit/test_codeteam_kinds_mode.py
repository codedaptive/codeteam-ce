import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_kinds_mode", ROOT / "share" / "codeteam_kinds_mode.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode


@pytest.mark.parametrize("environ, expected", [
    ({"CODETEAM_KINDS_BY_NAME": "1"}, "by-name"),
    ({"CODETEAM_KINDS_BY_NAME": " 1 "}, "by-name"),
    ({"CODETEAM_KINDS_BY_NAME": "1\n"}, "by-name"),
    ({}, None),
    ({"CODETEAM_KINDS_BY_NAME": ""}, None),
    ({"CODETEAM_KINDS_BY_NAME": "0"}, None),
    ({"CODETEAM_KINDS_BY_NAME": "yes"}, None),
    ({"CODETEAM_KINDS_BY_NAME": "true"}, None),
    ({"CODETEAM_KINDS_BY_NAME": "11"}, None),
    ({"KINDS_BY_NAME": "1"}, None),
])
def test_only_exactly_one_after_strip_turns_kinds_on(environ, expected):
    assert module.kinds_mode(environ) == expected
