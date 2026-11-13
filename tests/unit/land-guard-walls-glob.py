#!/usr/bin/env -S python3 -u
"""Landing gives a zone from a manifest glob the reference docs zone-docs.json names for its folder, as the zone guard
does (2026-11-12: an app is apps/* and INSTALLER_INTERFACE.md is its by zone-docs.json, but landing built
its walls with an empty zone and refused the doc)."""
import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_glob_walls", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

DOCS = ("docs/reference/INSTALLER_INTERFACE.md", "docs/_public/reference/INSTALLER_INTERFACE.md")


def team(d, lanes, zones):
    root = Path(d)
    (root / "team").mkdir()
    (root / "team" / "team.json").write_text(json.dumps({"lanes": {}}))
    manifest = root / "t.toml"
    manifest.write_text("")
    return SimpleNamespace(m={"lanes": lanes}, zones=zones, root=root, manifest=manifest)


def zone_docs(home, mapping):
    """codeteam_home with its own zone/zone-docs.json, so the test does not depend on the repo's map."""
    home = Path(home)
    (home / "zone").mkdir()
    (home / "zone" / "zone-docs.json").write_text(json.dumps(mapping))
    (home / "share").symlink_to(ROOT / "share")
    return home


def test_a_glob_zone_owns_the_docs_zone_docs_names_for_its_folder():
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as h:
        home = zone_docs(h, {"INSTALLER": "apps/acmex"})
        with patch.object(cl, "HERE", home / "bin"):
            t = team(d, [{"glob": "apps/*", "role": "zone"}],
                     {"acmex": ["apps/acmex"], "acme-mgr": ["apps/acme-mgr"]})
            walls = cl.guard_walls(t, "acmex")
            assert walls is not None
            assert walls.zone == "apps/acmex", walls.zone
            for f in DOCS:
                assert walls.owns_doc(f), f
            assert not any(cl.guard_walls(t, "acme-mgr").owns_doc(f) for f in DOCS)


def test_a_named_lane_keeps_its_own_path():
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as h:
        home = zone_docs(h, {"INSTALLER": "apps/acmex"})
        with patch.object(cl, "HERE", home / "bin"):
            t = team(d, [{"name": "tooling", "path": ".", "owns": ["tools"], "role": "zone"}], {"tooling": ["tools"]})
            assert cl.guard_walls(t, "tooling").zone == "."


if __name__ == "__main__":
    test_a_glob_zone_owns_the_docs_zone_docs_names_for_its_folder()
    test_a_named_lane_keeps_its_own_path()
    print("all passed")
