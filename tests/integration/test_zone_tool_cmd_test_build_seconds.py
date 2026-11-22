import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("zone_tool_cmd_test_build_seconds", str(ROOT / "bin" / "zone-tool"))
zone_tool = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(zone_tool)


def test_cmd_test_records_zero_build_seconds_when_command_does_not_build(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("CODETEAM_QUEUE_DIR", str(queue))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("ZONE_KEY_DIRS", "")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)

    subprocess.run(["git", "-c", "init.templateDir=", "init", "-q"], check=True)
    subprocess.run(["git", "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "initial"], check=True)

    assert zone_tool.cmd_test(["--", sys.executable, "-c", "print('ok')"]) == 0
    record = json.loads((repo / ".test-record.json").read_text())
    assert record["build_seconds"] == 0.0
