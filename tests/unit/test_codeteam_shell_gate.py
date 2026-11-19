import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_shell_gate", ROOT / "share" / "codeteam_shell_gate.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
sys.path.insert(0, str(ROOT / "share"))
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode
    sys.path.pop(0)

PLAIN = "#!/bin/bash\necho hello\n"
READS_GROUP = '#!/bin/bash\n[ "${CODETEAM_TEST_GROUP:-unit}" = integration ] || exit 0\n'


def script(tmp_path: Path, rel: str, text: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_plain_script_is_skipped_as_unit_in_an_integration_run(tmp_path):
    path = script(tmp_path, "pkg/tests/t.sh", PLAIN)
    assert module.shell_skip_kind(path, "pkg/tests/t.sh", "integration") == "unit"


def test_plain_script_runs_in_a_unit_run(tmp_path):
    path = script(tmp_path, "pkg/tests/t.sh", PLAIN)
    assert module.shell_skip_kind(path, "pkg/tests/t.sh", "unit") is None


@pytest.mark.parametrize("group", ["unit", "integration", "validation"])
def test_script_that_reads_the_group_runs_in_every_group(tmp_path, group):
    path = script(tmp_path, "pkg/tests/t.sh", READS_GROUP)
    assert module.shell_skip_kind(path, "pkg/tests/t.sh", group) is None


def test_script_under_an_integration_folder_is_skipped_as_integration_in_a_unit_run(tmp_path):
    path = script(tmp_path, "pkg/tests/integration/t.sh", PLAIN)
    assert module.shell_skip_kind(path, "pkg/tests/integration/t.sh", "unit") == "integration"


def test_script_under_an_integration_folder_runs_in_an_integration_run(tmp_path):
    path = script(tmp_path, "pkg/tests/integration/t.sh", PLAIN)
    assert module.shell_skip_kind(path, "pkg/tests/integration/t.sh", "integration") is None
