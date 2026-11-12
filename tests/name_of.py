"""Print codeteam's repo name for a path (used by tests/run.sh)."""
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

tool = Path(__file__).resolve().parent.parent / "bin" / "codeteam"
spec = importlib.util.spec_from_loader("codeteam", importlib.machinery.SourceFileLoader("codeteam", str(tool)))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.repo_name_of(sys.argv[1]))
