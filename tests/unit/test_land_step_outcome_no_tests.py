import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader("land_step_no_tests", str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
land = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(land)


def test_outer_no_tests_overrides_nested_hung():
    text = "zone-test: HUNG: nested\n...\nzone-test: NO TESTS (exit 0); record /r.json\n"
    assert land.step_outcome(0, text) == "PASS"
