import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_folder_kind", ROOT / "share" / "codeteam_folder_kind.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode


@pytest.mark.parametrize("rel, expected", [
    ("zone/tests/integration/test_a.py", "integration"),
    ("tests/validation/test_x.py", "validation"),
    ("tests/unit/own.py", "unit"),
    ("v2/tests/test_v2.py", None),
    ("zone/tests/integration/validation/t.py", "validation"),
    ("tests/validation/unit/t.py", "unit"),
    ("a/integration.py", None),
    ("a/integration", None),
    ("tests/integrations/t.py", None),
    ("./zone/tests/integration/t.sh", "integration"),
])
def test_folder_kind(rel, expected):
    assert module.folder_kind(rel) == expected
