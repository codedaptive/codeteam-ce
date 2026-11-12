import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def codeteam():
    environment = os.environ.copy()
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        if "herdr" in os.environ.get("SSH_AUTH_SOCK", ""):
            os.environ.pop("SSH_AUTH_SOCK")
        for name in (
            "CT_COMPACT_HOURS",
            "CT_EXIT_HOURS",
            "CT_SWAP_IDLE_MIN",
            "CT_API_RESUME_PER_RUN",
        ):
            os.environ.pop(name, None)
        loader = importlib.machinery.SourceFileLoader("codeteam", str(ROOT / "bin" / "codeteam"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
        os.environ.clear()
        os.environ.update(environment)


def test_relink_creates_session_folder_but_skips_other_missing_folders(codeteam, monkeypatch, tmp_path):
    class FakeTeam:
        assistants = ("Nagatha", "OwnHome", "External")

        def tiers(self):
            return ("integration",)

        def tier_wt(self, tier):
            return tmp_path / "checkouts" / tier

        def tier_dir(self, tier):
            return tmp_path / tier

        def managed(self, name):
            return name != "External"

        def tier_of(self, name):
            return "integration" if name != "OwnHome" else None

        def assistant_home(self, name):
            return tmp_path / "homes" / name

        def assistant_cwd(self, name):
            return tmp_path / "integration" / name

        def ledger(self, name):
            return tmp_path / "ledgers" / name

    calls = []

    def provision(team, folder, memory, *, quiet):
        calls.append((folder, memory, quiet))
        return True

    monkeypatch.setattr(codeteam, "provision_claude", provision)
    monkeypatch.setattr(codeteam, "foreign_claude", lambda path: False)
    monkeypatch.setattr(codeteam, "lane_cwd", lambda team, name, lane: tmp_path / "lanes" / name)
    monkeypatch.setattr(codeteam, "say_line", lambda line: None)
    (tmp_path / "integration" / "External").mkdir(parents=True)

    codeteam.relink_claude(FakeTeam(), {"lanes": {"cli": {}}})

    assert (tmp_path / "integration" / "Nagatha").is_dir()
    assert calls == [(tmp_path / "integration" / "Nagatha", tmp_path / "integration" / "agent-memory", True)]
    assert not (tmp_path / "homes" / "OwnHome").exists()
    assert not (tmp_path / "lanes" / "cli").exists()
    assert not (tmp_path / "checkouts" / "integration").exists()
