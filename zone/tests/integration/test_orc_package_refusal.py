import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[3] / "share" / "claude-hooks"
sys.path.insert(0, str(HOOKS))
import orc_package_refusal


@pytest.fixture
def team(tmp_path, monkeypatch):
    root = tmp_path / "team-x"
    repo = tmp_path / "repo"
    (root / "team").mkdir(parents=True)
    (repo / ".git").mkdir(parents=True)
    manifest = tmp_path / "team.toml"
    manifest.write_text(f"worktree_root = {json.dumps(str(root))}\nrepo = {json.dumps(str(repo))}\n")
    lanes = {"Widget": {"path": "packages/widget"}}
    fake = types.ModuleType("lane_walls")
    fake.ORCHESTRATOR = "orchestrator"
    fake.Walls = object
    fake.load_walls = lambda **kwargs: types.SimpleNamespace(lane="orc", lanes=lanes)
    fake.refused_by = lambda rel, walls: "Widget" if rel == "packages/widget" or rel.startswith("packages/widget/") else "orchestrator"
    monkeypatch.setitem(sys.modules, "lane_walls", fake)
    spec = importlib.util.spec_from_file_location("orc_package_refusal_zut", HOOKS / "orc_package_refusal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return types.SimpleNamespace(root=root, repo=repo, manifest=manifest, home=tmp_path / "home", lanes=lanes,
                                 refuse=module.orc_package_refusal)


def package(root, path="packages/widget"):
    folder = root / path
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Cargo.toml").touch()
    return folder


def test_lane_package_refusal_names_package_and_lane(team):
    folder = package(team.repo)
    reason = team.refuse(folder / "src/lib.rs", team.manifest, team.home)
    assert "packages/widget" in reason
    assert "code package" in reason
    assert "Widget" in reason
    assert "send" in reason


def test_uncovered_package_has_no_lane(team):
    folder = package(team.repo, "tools/stray")
    reason = team.refuse(folder / "x.py", team.manifest, team.home)
    assert "tools/stray" in reason
    assert "has no lane" in reason


@pytest.mark.parametrize("path", ["README.md", "Cargo.toml", "docs/x.md", "teams/x.toml", "scripts/x.sh"])
def test_non_package_paths_are_allowed(team, path):
    assert team.refuse(team.repo / path, team.manifest, team.home) is None


def test_parent_holding_package_is_refused(team):
    package(team.repo)
    reason = team.refuse(team.repo / "packages", team.manifest, team.home)
    assert "packages/widget" in reason
    assert "Widget" in reason


def test_work_order_tree_by_position_without_git_marker(team):
    top = team.root / "wo/orc/change"
    folder = package(top)
    reason = team.refuse(folder / "src/lib.rs", team.manifest, team.home)
    assert "packages/widget" in reason
    assert "Widget" in reason


def test_work_order_root_marker_is_not_a_package(team):
    top = team.root / "wo/orc/change"
    top.mkdir(parents=True)
    (top / "Cargo.toml").touch()
    assert team.refuse(top / "Cargo.toml", team.manifest, team.home) is None


def test_package_without_tree_top_has_no_lane(team):
    folder = package(team.root, "scratch/packages/widget")
    reason = team.refuse(folder / "src/lib.rs", team.manifest, team.home)
    assert "scratch/packages/widget" in reason
    assert "has no lane" in reason


def test_glob_matches_package(team):
    package(team.repo)
    reason = team.refuse(team.repo / "packages/*", team.manifest, team.home)
    assert "packages/widget" in reason
    assert "Widget" in reason


def test_glob_with_no_matches_inside_package(team):
    folder = package(team.repo)
    reason = team.refuse(folder / "src/*.new", team.manifest, team.home)
    assert "packages/widget" in reason
    assert "Widget" in reason


def test_outside_team_and_repo_is_allowed(team, tmp_path):
    folder = package(tmp_path, "outside/pkg")
    assert team.refuse(folder / "src/x.rs", team.manifest, team.home) is None


@pytest.mark.parametrize("contents", [None, "invalid = [\n"])
def test_missing_or_invalid_manifest_is_allowed(team, contents):
    folder = package(team.repo)
    if contents is None:
        team.manifest.unlink()
    else:
        team.manifest.write_text(contents)
    assert team.refuse(folder / "src/x.rs", team.manifest, team.home) is None
