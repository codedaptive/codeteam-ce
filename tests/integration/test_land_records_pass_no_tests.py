import importlib.machinery
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration", reason="integration group only")

loader = importlib.machinery.SourceFileLoader("land_records_no_tests", str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
land = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(land)


def test_no_tests_record_counts_as_passing(tmp_path):
    record = tmp_path / ".test-record-ab.json"
    record.write_text(json.dumps({"result": "NO TESTS"}))
    assert land.records_pass(f"zone-test: NO TESTS (exit 0); record {record}\n") is True
