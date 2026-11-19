import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_v2 import FakeTeam, Runtime        # puts v2/ on sys.path
from codeteam2.team import CT_HOME
from conftest import integration_module  # noqa: E402

# integration: every case here runs real git (the repo fixture; backup_runtime's remote and v1's git calls) or
# /bin/sh over fake tools on PATH (rule 11). The job's own choices are unit-tested in
# test_backup_sweep.py.
pytestmark = integration_module


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


# The hourly backup's one background job: push, then v1's branch sweep. Cron has not reached GitHub since
# 2026-11-13 14:10, and the loop has, so the GitHub half of the sweep runs here.

PRODUCTION_MANIFEST = str(CT_HOME / "teams" / "fake.toml")       # a team cron's sweep covered


def backup_runtime(repo, monkeypatch, branches, manifest=PRODUCTION_MANIFEST):
    git(repo, "remote", "add", "origin", str(repo / "origin.git"))
    rt = runtime(repo)
    rt.team.backup_min, rt.team.manifest, rt.team.t.backup = 60, manifest, True
    rt.backup_branches = lambda: branches
    started, real = [], subprocess.Popen

    def popen(argv, **kw):          # only the backup's job is caught; v1's git calls run for real
        if argv[:1] != ["/bin/sh"]:
            return real(argv, **kw)
        started.append((argv, kw))
    monkeypatch.setattr(subprocess, "Popen", popen)
    return rt, started


def test_backup_pushes_then_sweeps_in_one_background_job(repo, monkeypatch):
    rt, started = backup_runtime(repo, monkeypatch, ["lane/a", "exchange"])
    rt.backup({}, 10 ** 6)
    assert len(started) == 1, started
    argv, kw = started[0]
    assert argv == ["/bin/sh", "-c", Runtime.PUSH_THEN_SWEEP, "backup",
                    "refs/heads/lane/a:refs/heads/lane/a", "refs/heads/exchange:refs/heads/exchange"]
    env = kw["env"]
    assert env["CT_REPO"] == str(repo) and env["CT_MANIFEST"] == PRODUCTION_MANIFEST
    assert env["CT_V1"].endswith("/bin/codeteam") and Path(env["CT_V1"]).is_file(), env["CT_V1"]
    assert kw["start_new_session"] and kw["stdin"] == subprocess.DEVNULL


def test_backup_with_nothing_to_push_still_sweeps(repo, monkeypatch):
    rt, started = backup_runtime(repo, monkeypatch, [])
    rt.backup({}, 10 ** 6)
    assert [argv[4:] for argv, _ in started] == [[]], started


def test_a_manifest_outside_teams_is_pushed_and_never_swept(repo, monkeypatch):
    """A v5.5 checkout's loop may run this codeteam2 on a manifest in its own repo; that team runs its own tools, and this
    checkout's sweep never deletes its branches (cron's sweep covered teams/*.toml only)."""
    rt, started = backup_runtime(repo, monkeypatch, ["lane/a"], manifest="/elsewhere/teams/jj.toml")
    rt.backup({}, 10 ** 6)
    assert [(argv[4:], kw["env"]["CT_MANIFEST"]) for argv, kw in started] == [
        (["refs/heads/lane/a:refs/heads/lane/a"], "")], started


def test_a_manifest_outside_teams_with_nothing_to_push_starts_nothing(repo, monkeypatch):
    rt, started = backup_runtime(repo, monkeypatch, [], manifest="/elsewhere/teams/jj.toml")
    rt.backup({}, 10 ** 6)
    assert started == []


def fake_tools(tmp_path, push_rc):
    """A git and a v1 that write their arguments to calls.txt; the git push answers push_rc, and 1 for any push naming
    "refused" (a ref the repo's pre-push hook turns down: the hook fails the whole push). git rev-parse answers
    quietly: no branch for a ref naming "gone", one for any other."""
    calls, tools = tmp_path / "calls.txt", tmp_path / "tools"
    tools.mkdir()
    for name, rc in (("git", push_rc), ("codeteam", 0)):
        verify = ('if [ "$3" = rev-parse ]; then case "$*" in *gone*) exit 1;; esac; exit 0; fi\n'
                  f'case "$*" in *refused*) echo "{name} $*" >> "{calls}"; exit 1;; esac\n') if name == "git" else ""
        (tools / name).write_text(f'#!/bin/sh\n{verify}echo "{name} $*" >> "{calls}"\nexit {rc}\n')
        (tools / name).chmod(0o755)
    return calls, tools


def run_job(tools, *refspecs, manifest="/m.toml", out=None):
    env = {"PATH": f"{tools}:/usr/bin:/bin", "CT_REPO": "/r", "CT_V1": str(tools / "codeteam"),
           "CT_MANIFEST": manifest}
    return subprocess.run(["/bin/sh", "-c", Runtime.PUSH_THEN_SWEEP, "backup", *refspecs], env=env,
                          stdout=out).returncode


def test_the_sweep_runs_after_the_push_whatever_the_push_answered(tmp_path):
    calls, tools = fake_tools(tmp_path, push_rc=1)
    assert run_job(tools, "refs/heads/a:refs/heads/a") == 0
    assert calls.read_text().splitlines() == ["git -C /r push --force origin refs/heads/a:refs/heads/a",
                                              "codeteam sweep-branches /m.toml"]


def test_with_no_refspecs_the_job_only_sweeps(tmp_path):
    calls, tools = fake_tools(tmp_path, push_rc=0)
    assert run_job(tools) == 0
    assert calls.read_text().splitlines() == ["codeteam sweep-branches /m.toml"]


def test_with_no_manifest_the_job_only_pushes(tmp_path):
    calls, tools = fake_tools(tmp_path, push_rc=0)
    assert run_job(tools, "refs/heads/a:refs/heads/a", manifest="") == 0
    assert calls.read_text().splitlines() == ["git -C /r push --force origin refs/heads/a:refs/heads/a"]


def test_a_branch_gone_since_the_list_is_left_out_of_the_push(tmp_path):
    """2026-11-14: a landing deleted a docs-stamp branch between the list and the push, and git refused
    the whole push (src refspec does not match any), so none of the 98 branches went."""
    calls, tools = fake_tools(tmp_path, push_rc=0)
    assert run_job(tools, "refs/heads/a:refs/heads/a", "refs/heads/gone:refs/heads/gone", "refs/heads/b:refs/heads/b") == 0
    assert calls.read_text().splitlines() == [
        "git -C /r push --force origin refs/heads/a:refs/heads/a refs/heads/b:refs/heads/b",
        "codeteam sweep-branches /m.toml"]


def test_when_every_branch_is_gone_only_the_sweep_runs(tmp_path):
    calls, tools = fake_tools(tmp_path, push_rc=0)
    assert run_job(tools, "refs/heads/gone:refs/heads/gone") == 0
    assert calls.read_text().splitlines() == ["codeteam sweep-branches /m.toml"]


def test_a_refused_branch_holds_back_only_itself(tmp_path):
    """acme, 2026-11-16 09:05-13:05: its pre-push hook refused wo/orc/ce-zone-test-one-twins, which fails the
    whole push, and five hourly backups of about 99 branches went nowhere."""
    calls, tools = fake_tools(tmp_path, push_rc=0)
    log = tmp_path / "backup.log"
    with log.open("w") as out:
        assert run_job(tools, "refs/heads/a:refs/heads/a", "refs/heads/refused:refs/heads/refused",
                       "refs/heads/b:refs/heads/b", out=out) == 0
    assert calls.read_text().splitlines() == [
        "git -C /r push --force origin refs/heads/a:refs/heads/a refs/heads/refused:refs/heads/refused "
        "refs/heads/b:refs/heads/b",
        "git -C /r push --force origin refs/heads/a:refs/heads/a",
        "git -C /r push --force origin refs/heads/refused:refs/heads/refused",
        "git -C /r push --force origin refs/heads/b:refs/heads/b",
        "codeteam sweep-branches /m.toml"]
    assert log.read_text().splitlines() == ["backup: the push of 3 branches failed; pushing each on its own",
                                            "backup: not pushed: refs/heads/refused"]


def test_a_whole_push_that_goes_is_not_repeated_branch_by_branch(tmp_path):
    calls, tools = fake_tools(tmp_path, push_rc=0)
    assert run_job(tools, "refs/heads/a:refs/heads/a", "refs/heads/b:refs/heads/b") == 0
    assert calls.read_text().splitlines() == [
        "git -C /r push --force origin refs/heads/a:refs/heads/a refs/heads/b:refs/heads/b",
        "codeteam sweep-branches /m.toml"]
