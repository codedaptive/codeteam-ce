"""Manifest wiring for the idle exit timeout."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2.team import Team  # noqa: E402
from conftest import integration_module  # noqa: E402

pytestmark = integration_module


@pytest.mark.parametrize("setting,expected", [("", 60), ("idle_exit_h = 0\n", 0),
                                               ("idle_exit_h = 2\n", 120)],
                         ids=["default", "disabled", "two-hours"])
def test_manifest_idle_exit_minutes(tmp_path, monkeypatch, setting, expected):
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setenv("CODETEAM_QUEUE_DIR", str(queue))
    manifest = tmp_path / "team.toml"
    manifest.write_text(f'product = "scratch"\nrepo = "{tmp_path / "repo"}"\nbase = "main"\n'
                        f'worktree_root = "{tmp_path / "root"}"\n[v2]\n{setting}')
    assert Team(manifest).idle_exit_min == expected
