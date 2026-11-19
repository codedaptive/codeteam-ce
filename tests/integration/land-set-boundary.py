#!/usr/bin/env -S python3 -u
"""Stages 6 and 7 treat a --with set's landing as one step: Stage 4 merges the members one by one and moves landing
once, to the last, so the commits before it are never validated or promoted (acme's reindex
set landed as d5e8bf8a9b, e2016f811f, db0e5c3f12; Stage 6 passed at e2016f811f, the middle one, and Stage 7 promoted
WidgetStoreKit's changed API without acmex's caller change). Git is faked; records live in a temp folder.
An integration test: stage6_target reads the landed log and the recheck rows under the real Lock. The
unit tests are in tests/unit/land-set-boundary.py."""
import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_set_boundary", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

SET = ["corpus", "glk", "acmex"]


def team_at(root):
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{root / "repo"}"\nworktree_root = "{root / "team"}"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n[land]\nseed_index = false\n')
    team = cl.Team(manifest)
    team.notify = Mock()
    return team


def landed(team, *rows):
    with open(team.dir / "landed.log", "a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def acme_rows(team, named=True):
    """acme's case: one lone landing, the three-member set, a lone landing after it, and a promote row."""
    def row(wo, commit):
        return {"wos": [wo], "hash": commit, **({"set": SET} if named and wo in SET else {})}
    landed(team, row("before", "f47"), row("corpus", "d5e"), row("glk", "e20"), row("acmex", "db0"),
           row("tooling", "d15"), {"promote": "f47", "to": "develop"})


def test_stage6_target_reads_the_sets_from_landed_log():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        acme_rows(team)
        (team.dir / "recheck.jsonl").write_text(json.dumps({"M": "db0", "wo": "corpus", "set": SET}) + "\n")
        after = {"db0": {"db0", "d15"}}
        with patch.object(cl, "out", return_value="d15\ndb0\ne20\nd5e\nf47\n"), \
                patch.object(cl, "ancestry", return_value=lambda a, b: b in after.get(a, {a})):
            assert cl.stage6_target(team) == "f47"


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:          # report every case, then fail once
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
