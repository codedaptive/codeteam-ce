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


class FakeTeam:
    def __init__(self, manifest_data):
        self.m = manifest_data
        self.manifest = "/x/team.toml"


def test_promote_refuses_land_team_before_loading(codeteam, monkeypatch):
    calls = []

    def unexpected_load(*args, **kwargs):
        calls.append("load_team")
        pytest.fail("load_team called before promote refusal")

    def unexpected_worktree(*args, **kwargs):
        calls.append("tier_worktree")
        pytest.fail("tier_worktree called before promote refusal")

    monkeypatch.setattr(codeteam, "load_team", unexpected_load)
    monkeypatch.setattr(codeteam, "tier_worktree", unexpected_worktree)

    with pytest.raises(SystemExit) as exc:
        codeteam.cmd_promote(FakeTeam({"land": {"enabled": True}}), None)

    message = str(exc.value)
    assert message.startswith("promote is off for this team: it lands with codeteam-land (spec v5).")
    assert "codeteam-land /x/team.toml promote" in message
    assert "land <work order>" not in message
    assert calls == []


@pytest.mark.parametrize("manifest_data", [{}, {"land": {"enabled": False}}], ids=["absent", "disabled"])
def test_refuse_promote_allows_teams_without_landing(codeteam, manifest_data):
    assert codeteam.refuse_if_landing(FakeTeam(manifest_data), "promote") is None


def test_refuse_push_up_message_is_unchanged(codeteam):
    with pytest.raises(SystemExit) as exc:
        codeteam.refuse_if_landing(FakeTeam({"land": {"enabled": True}}), "push-up")

    assert str(exc.value) == (
        "push-up is off for this team: it lands with codeteam-land (spec v5). "
        "Queue a finished work order with: codeteam-land /x/team.toml land <work order>"
    )
