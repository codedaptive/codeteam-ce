import subprocess
from types import SimpleNamespace

import pytest

from test_v2 import FakeTeam, Runtime


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "initial")
    for branch in ("lane/a", "exchange", "integration"):
        git(tmp_path, "branch", branch)
    return tmp_path


def runtime(repo, *, lab=False, manifest=None):
    team = FakeTeam(repo, [])
    team.t = SimpleNamespace(repo=repo, prefix="lane/", exchange="exchange", integration="integration",
                             base="main", lab=lab, m=manifest if manifest is not None else {})
    return Runtime(team, herdr=object(), store=object(), transport=object())


def test_landing_team_includes_default_landing_branch(repo):
    git(repo, "branch", "landing")
    assert runtime(repo, manifest={"land": {"enabled": True}}).backup_branches() == [
        "lane/a", "exchange", "integration", "landing"
    ]


def test_landing_team_omits_missing_landing_branch(repo):
    assert runtime(repo, manifest={"land": {"enabled": True}}).backup_branches() == [
        "lane/a", "exchange", "integration"
    ]


def test_landing_team_includes_custom_landing_not_default(repo):
    git(repo, "branch", "staged")
    git(repo, "branch", "landing")
    assert runtime(repo, manifest={"land": {"enabled": True, "landing": "staged"}}).backup_branches() == [
        "lane/a", "exchange", "integration", "staged"
    ]


def test_lab_team_omits_landing_branch(repo):
    git(repo, "branch", "landing")
    assert runtime(repo, lab=True, manifest={"land": {"enabled": True}}).backup_branches() == [
        "lane/a", "exchange", "integration"
    ]


def test_v1_team_omits_landing_branch(repo):
    git(repo, "branch", "landing")
    assert runtime(repo, manifest={}).backup_branches() == ["lane/a", "exchange", "integration"]
