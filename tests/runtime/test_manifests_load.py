"""Check checked-in manifests with the CLI's team loader and its lab tier rule.

The import fixture restores environment changes, avoids the herdr socket lookup,
clears import-time numeric settings, and prevents bytecode writes beside the CLI.
HOME is redirected as insurance against filesystem side effects during construction.
"""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = sorted((ROOT / "teams").glob("*.toml"))


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


def test_manifests_exist():
    assert MANIFESTS, "No team manifests found"


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda path: path.name)
def test_manifest_loads(path, codeteam, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    try:
        codeteam.Team(path)
    except SystemExit as exc:
        pytest.fail(f"{path.name}: the codeteam loader rejects it: {exc.code}")


def test_lab_assistant_rejects_integration_tier(codeteam, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "lab.toml"
    path.write_text(
        'product = "scratch"\n'
        f'repo = {json.dumps(str(tmp_path / "repo"))}\n'
        'base = "main"\n'
        'mode = "lab"\n'
        '[[assistants]]\n'
        'name = "test-assistant"\n'
        'tier = "integration"\n'
    )

    with pytest.raises(SystemExit) as exc:
        codeteam.Team(path)
    assert "tier must be one of design" in str(exc.value.code)
    assert "test-assistant" in str(exc.value.code)
