#!/usr/bin/env -S python3 -u
"""The gate's environment expands {root} and {home} in a team's [env], as v1 does for sessions (2026-11-08).
Moved from tests/integration, since it tests one function: a manifest in a temp folder.
Isolated: the team names its own TMPDIR, so team_env makes no folder and runs no
tmutil; HOME is a temp folder; a command run while the case runs fails it."""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

W = Path(tempfile.mkdtemp(prefix="land-env-"))
# Restart markers and stage admissions live beside the queue; keep them out of the checkout.
os.environ["CODETEAM_QUEUE_DIR"] = str(W / "queue")

HOME = Path(__file__).resolve().parents[2]
ld = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp)
with patch("subprocess.run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    ld.exec_module(cl)


def ran(*args, **kwargs):
    raise AssertionError(f"team_env ran a command: {args[0] if args else kwargs}")


def case():
    (W / "repo").mkdir()
    (W / "team.toml").write_text(f'repo = "{W / "repo"}"\nworktree_root = "{W / "root"}"\n'
                                 f'[env]\nTMPDIR = "{W / "tmp"}/"\n'
                                 'A = "{root}/acme/current"\nB = "{home}/x"\nC = "~/y"\n')
    with (patch.dict(os.environ, {"HOME": str(W / "home")}),
          patch("subprocess.run", side_effect=ran), patch("subprocess.Popen", side_effect=ran)):
        team = cl.Team(str(W / "team.toml"), create=False)
        env = cl.team_env(team)
    want = {"A": f"{team.root}/acme/current", "B": f"{team.root}/team/x", "C": f"{W / 'home'}/y"}
    got = {k: env[k] for k in want}
    return got == want and not (W / "root").exists(), got


def test_landing_disables_incremental_for_every_group():
    (W / "repo").mkdir(exist_ok=True)
    (W / "incremental.toml").write_text(
        f'repo = "{W / "repo"}"\nworktree_root = "{W / "root"}"\n'
        f'[env]\nTMPDIR = "{W / "tmp"}/"\nCARGO_INCREMENTAL = "1"\n')
    original = {k: v for k, v in os.environ.items() if k != "CARGO_INCREMENTAL"}
    with (patch.dict(os.environ, original, clear=True),
          patch("subprocess.run", side_effect=ran), patch("subprocess.Popen", side_effect=ran)):
        team = cl.Team(str(W / "incremental.toml"), create=False)
        envs = {group: cl.team_env(team, group) for group in ("unit", "integration", "validation", None)}
        assert team.m["env"]["CARGO_INCREMENTAL"] == "1"
        assert dict(os.environ) == original
        assert not (W / "root").exists()
        assert {group: env["CARGO_INCREMENTAL"] for group, env in envs.items()} == {
            "unit": "0", "integration": "0", "validation": "0", None: "0"}


if sys.argv[1:] == ["incremental"]:
    try:
        test_landing_disables_incremental_for_every_group()
    finally:
        shutil.rmtree(W, ignore_errors=True)
else:
    ok, got = case()
    print(("  PASS" if ok else "  FAIL") + " {root}, {home} and ~ are expanded", "" if ok else got)
    if ok:
        try:
            test_landing_disables_incremental_for_every_group()
        finally:
            shutil.rmtree(W, ignore_errors=True)
    else:
        print(f"  ({W} kept for a look)")
    sys.exit(0 if ok else 1)
