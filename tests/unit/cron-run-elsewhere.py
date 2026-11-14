#!/usr/bin/env -S python3 -u
"""A team another checkout's tools run is left alone by this checkout's cron jobs:
acme's launchd land job runs a v5.5 checkout's codeteam-land on that checkout's teams/acme.toml, so this checkout's
stale teams/acme.toml must not drive an hourly v1 sweep, rotate, tick or patrol, or a minute wake, on acme. The rule is
the watchdog's runs_from: the land job names another checkout's tool and another manifest. Temp folders only."""
import contextlib
import importlib.machinery
import importlib.util
import io
import plistlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("codeteam_run_elsewhere", str(ROOT / "bin" / "codeteam"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


ct = load()


def manifest(folder, name="acme"):
    folder.mkdir(parents=True, exist_ok=True)
    m = folder / f"{name}.toml"
    m.write_text(f'product = "{name}"\nrepo = "{folder / "repo"}"\nbase = "main"\nworktree_root = "{folder / "team"}"\n')
    return m


def land_job(agents, name, land, manifest_path):
    agents.mkdir(parents=True, exist_ok=True)
    with open(agents / f"{ct.LAUNCHD_PREFIX}.codeteam-land.{name}.plist", "wb") as f:
        plistlib.dump({"Label": f"{ct.LAUNCHD_PREFIX}.codeteam-land.{name}",
                       "ProgramArguments": [sys.executable, str(land), str(manifest_path), "run"]}, f)


def setup(d):
    """This checkout's teams/ with a copy of acme's manifest; another checkout holding the manifest of record."""
    teams, agents, other = d / "teams", d / "LaunchAgents", d / "other-checkout"
    copy = manifest(teams)
    record = manifest(other / "teams")
    return teams, agents, other, copy, record


def test_a_copy_of_a_team_another_checkout_runs_stands_aside():
    with tempfile.TemporaryDirectory() as d:
        teams, agents, other, copy, record = setup(Path(d))
        land_job(agents, "acme", other / "bin" / "codeteam-land", record)
        assert ct.run_elsewhere(ct.Team(str(copy)), agents=agents, teams=teams) == str(record)


def test_a_team_this_checkouts_land_tool_runs_is_this_checkouts():
    with tempfile.TemporaryDirectory() as d:
        teams, agents, other, copy, record = setup(Path(d))
        land_job(agents, "acme", ct.TOOL_DIR / "bin" / "codeteam-land", record)
        assert ct.run_elsewhere(ct.Team(str(copy)), agents=agents, teams=teams) is None


def test_the_manifest_the_land_job_names_is_its_own_record():
    """The other checkout running its own teams/acme.toml: the job names that very manifest."""
    with tempfile.TemporaryDirectory() as d:
        teams, agents, other, copy, record = setup(Path(d))
        land_job(agents, "acme", other / "bin" / "codeteam-land", copy)
        assert ct.run_elsewhere(ct.Team(str(copy)), agents=agents, teams=teams) is None


def test_a_manifest_outside_this_checkouts_teams_is_never_a_copy():
    """Test teams and other clones' manifests: the cron loop covers teams/*.toml only."""
    with tempfile.TemporaryDirectory() as d:
        teams, agents, other, copy, record = setup(Path(d))
        land_job(agents, "acme", other / "bin" / "codeteam-land", record)
        elsewhere = manifest(Path(d) / "scratch")
        assert ct.run_elsewhere(ct.Team(str(elsewhere)), agents=agents, teams=teams) is None


def test_no_land_job_or_an_unreadable_one_is_this_checkouts():
    with tempfile.TemporaryDirectory() as d:
        teams, agents, other, copy, record = setup(Path(d))
        assert ct.run_elsewhere(ct.Team(str(copy)), agents=agents, teams=teams) is None
        agents.mkdir(parents=True, exist_ok=True)
        (agents / f"{ct.LAUNCHD_PREFIX}.codeteam-land.acme.plist").write_text("not a plist")
        assert ct.run_elsewhere(ct.Team(str(copy)), agents=agents, teams=teams) is None


def dispatch(cmd, copy, record):
    """main() for `codeteam <cmd> <copy>`, with run_elsewhere answering the record and every job refusing to run."""
    calls = []
    saved = {name: getattr(ct, name) for name in ("run_elsewhere", "cmd_sweep", "cmd_wake", "cmd_rotate")}
    ct.run_elsewhere = lambda t: str(record)
    for name in ("cmd_sweep", "cmd_wake", "cmd_rotate"):
        setattr(ct, name, lambda t, a, name=name: calls.append(name))
    argv, sys.argv = sys.argv, ["codeteam", cmd, str(copy)]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            ct.main()
    finally:
        sys.argv = argv
        for name, value in saved.items():
            setattr(ct, name, value)
    return calls, out.getvalue()


def test_cron_jobs_stand_aside_and_say_so_except_the_minute_wake():
    with tempfile.TemporaryDirectory() as d:
        teams, agents, other, copy, record = setup(Path(d))
        calls, out = dispatch("sweep", copy, record)
        assert calls == [] and "stands aside" in out and str(record) in out, (calls, out)
        calls, out = dispatch("rotate", copy, record)
        assert calls == [] and "stands aside" in out, (calls, out)
        calls, out = dispatch("wake", copy, record)
        assert calls == [] and out == "", (calls, out)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except Exception as e:                 # noqa: BLE001 - a test's failure of any kind is reported
            failed += 1
            print(f"  FAIL {test.__name__}: {e!r}")
    print("all passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
