#!/usr/bin/env -S python3 -u
"""Unit contracts for v5.2 removals."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HOME = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)

W = Path(tempfile.mkdtemp(prefix="land-v52-removed-"))
(W / "repo").mkdir()
(W / "team.toml").write_text(f'repo = "{W / "repo"}"\nworktree_root = "{W / "root"}"\n'
                             f'[env]\nTMPDIR = "{W}"\n')
team = cl.Team(str(W / "team.toml"))
failed = 0


def t(label, cond, detail):
    global failed
    print(f"  {'PASS' if cond else 'FAIL'} {label}" + (f" {detail}" if not cond else ""))
    failed += not cond


def refused(label, args):
    result = "returned normally"
    try:
        with patch.object(cl, "Team", side_effect=RuntimeError("manifest read")), contextlib.redirect_stderr(io.StringIO()):
            cl.main([str(W / "team.toml"), *args])
    except SystemExit as exc:
        result = exc.code
    except RuntimeError as exc:
        result = str(exc)
    t(label, result == 2, f"expected argparse exit 2 before manifest, got {result!r}")


refused("verdict refused", ["verdict", "wo1", "land"])
refused("fixes-base refused", ["fixes-base", "wo1"])
refused("base-clear refused", ["base-clear"])
refused("land-one --skip-review refused", ["land-one", "wo1", "--skip-review"])
refused("promote --accept refused", ["promote", "abc", "--accept", "reason"])

with patch.dict(os.environ, {}, clear=True):
    env = cl.team_env(team)
t("default environment omits ZONE_TEST_ONE_FLAGS", env.get("ZONE_TEST_ONE_FLAGS") == "", repr(env.get("ZONE_TEST_ONE_FLAGS")))
t("default environment omits ZONE_TEST_FLAGS", env.get("ZONE_TEST_FLAGS") == "", repr(env.get("ZONE_TEST_FLAGS")))
t("Team landing defaults to landing", team.landing == "landing", repr(getattr(team, "landing", None)))

(W / "custom.toml").write_text(f'repo = "{W / "repo"}"\nworktree_root = "{W / "root"}"\n'
                               f'[env]\nTMPDIR = "{W}"\nZONE_TEST_ONE_FLAGS = "custom-one"\n'
                               'ZONE_TEST_FLAGS = "custom-all"\n')
with patch.dict(os.environ, {}, clear=True):
    custom = cl.team_env(cl.Team(str(W / "custom.toml")))
t("manifest timeout flags are preserved", custom.get("ZONE_TEST_ONE_FLAGS") == "custom-one" and
  custom.get("ZONE_TEST_FLAGS") == "custom-all", repr((custom.get("ZONE_TEST_ONE_FLAGS"), custom.get("ZONE_TEST_FLAGS"))))

print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
