"""The loop's hourly backup job sweeps whether or not it pushes (D464, Orc-Codeteam-jj #4286). For a v2 team cron's
sweep leaves branches to this job (D452), so with backup off, no origin or backup_min 0 the job still starts, with
nothing to push. The job's shell script and v1's git are faked here; test_backup_branches.py runs them for real."""
import subprocess
from types import SimpleNamespace

from test_v2 import FakeTeam, Runtime        # puts v2/ on sys.path
from codeteam2.team import CT_HOME, v1

PRODUCTION_MANIFEST = str(CT_HOME / "teams" / "fake.toml")       # a team cron's sweep covered
HOUR = 3600


def job(tmp_path, monkeypatch, *, backup, backup_min=60, origin=True, manifest=PRODUCTION_MANIFEST):
    """A Runtime whose backup job is caught: started holds (refspecs, CT_MANIFEST) per job, gits v1's git calls."""
    team = FakeTeam(tmp_path, [])
    team.t = SimpleNamespace(repo=tmp_path, backup=backup)
    team.backup_min, team.manifest = backup_min, manifest
    rt = Runtime(team, log=lambda line: None, herdr=object(), store=object(), transport=object())
    rt.backup_branches = lambda: ["lane/a"]
    gits, started = [], []
    monkeypatch.setattr(v1, "git", lambda repo, *args, check=True: gits.append(args) or SimpleNamespace(
        returncode=0 if origin else 2, stdout="", stderr=""))
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: started.append((argv[4:], kw["env"]["CT_MANIFEST"])))
    return rt, started, gits


def test_backup_on_pushes_and_sweeps(tmp_path, monkeypatch):
    rt, started, gits = job(tmp_path, monkeypatch, backup=True)
    rt.backup({}, 10 ** 6)
    assert started == [(["refs/heads/lane/a:refs/heads/lane/a"], PRODUCTION_MANIFEST)]
    assert gits == [("remote", "get-url", "origin")]


def test_backup_off_still_sweeps_and_asks_git_nothing(tmp_path, monkeypatch):
    rt, started, gits = job(tmp_path, monkeypatch, backup=False)
    rt.backup({}, 10 ** 6)
    assert started == [([], PRODUCTION_MANIFEST)] and gits == []


def test_no_origin_still_sweeps(tmp_path, monkeypatch):
    rt, started, _ = job(tmp_path, monkeypatch, backup=True, origin=False)
    rt.backup({}, 10 ** 6)
    assert started == [([], PRODUCTION_MANIFEST)]


def test_backup_min_zero_sweeps_hourly_and_never_pushes(tmp_path, monkeypatch):
    rt, started, gits = job(tmp_path, monkeypatch, backup=True, backup_min=0)
    st = {}
    for now in (10 ** 6, 10 ** 6 + HOUR - 1, 10 ** 6 + HOUR):
        rt.backup(st, now)
    assert started == [([], PRODUCTION_MANIFEST)] * 2 and gits == []


def test_backup_off_outside_teams_starts_nothing_and_keeps_no_state(tmp_path, monkeypatch):
    """codeteam-jj's manifest: this checkout neither pushes (backup off) nor sweeps its branches."""
    rt, started, _ = job(tmp_path, monkeypatch, backup=False, manifest="/elsewhere/teams/jj.toml")
    st = {}
    rt.backup(st, 10 ** 6)
    assert started == [] and st == {}
