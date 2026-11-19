import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_shell_kind", ROOT / "share" / "codeteam_shell_kind.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
sys.path.insert(0, str(ROOT / "share"))
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode
    sys.path.pop(0)


@pytest.mark.parametrize("text, expected", [
    ('if [ "${CODETEAM_TEST_GROUP:-unit}" != validation ]; then\nfi\n', None),
    ('VAL=; [ "$CODETEAM_TEST_GROUP" = validation ] && VAL=1\n', None),
    ('test_group="${CODETEAM_TEST_GROUP:-${GROUP:-unit}}"\n', None),
    ('echo "${CODETEAM_TEST_GROUP-unset}"\n', None),
    ('echo "$GROUP"\n', None),
    ('echo "${GROUP-unset}"\n', None),
    ('echo "$GROUPS"\n', "unit"),
    ('echo "$GROUP_ID"\n', "unit"),
    ('echo "$CODETEAM_TEST_GROUPS"\n', "unit"),
    ('echo "$CODETEAM_TEST_GROUP_ID"\n', "unit"),
    ('export -n GROUP CODETEAM_TEST_GROUP\n', "unit"),
    ('env CODETEAM_TEST_GROUP=integration cmd\n', "unit"),
    ('unset CODETEAM_TEST_GROUP\n', "unit"),
    ('echo ok\n', "unit"),
])
def test_shell_variable_expansion_classifies_unnamed_file(tmp_path, text, expected):
    path = tmp_path / "test_case.sh"
    path.write_text(text)
    assert module.shell_test_kind(path, "tests/test_case.sh") == expected


def test_folder_kind_overrides_group_read(tmp_path):
    path = tmp_path / "test_case.sh"
    path.write_text('echo "$CODETEAM_TEST_GROUP"\n')
    assert module.shell_test_kind(path, "zone/tests/integration/test_case.sh") == "integration"


def test_unreadable_unnamed_file_defaults_to_unit(tmp_path):
    path = tmp_path / "test_case.sh"
    path.write_text('echo "$GROUP"\n')
    path.chmod(0)
    try:
        assert module.shell_test_kind(path, "tests/test_case.sh") == "unit"
    finally:
        path.chmod(0o600)
