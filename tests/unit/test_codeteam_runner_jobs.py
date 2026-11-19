"""share/codeteam_runner_jobs.py alone: the runner jobs whose launchd program is one checkout's
bin/codeteam-land, wherever their manifests live. after_promote with it: tests/unit/land-v52-restart.py.
"""
import importlib.util
import plistlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_runner_jobs", ROOT / "share" / "codeteam_runner_jobs.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode


def job(agents, label, program, manifest, command):
    agents.mkdir(parents=True, exist_ok=True)
    args = ["/opt/homebrew/opt/python@3.15/bin/python3.15", str(program), str(manifest), command]
    (agents / f"{label}.plist").write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": args}))


def test_a_fork_promote_finds_the_runners_of_its_program_and_not_production_s(tmp_path):
    fork, production, agents = tmp_path / "fork", tmp_path / "production", tmp_path / "LaunchAgents"
    job(agents, "com.codeteam.codeteam-land.sprocket", fork / "bin/codeteam-land", fork / "teams/sprocket.toml", "queue-run")
    job(agents, "com.codeteam.codeteam-validate.sprocket", fork / "bin/codeteam-land", fork / "teams/sprocket.toml",
        "validate-run")
    job(agents, "com.codeteam.codeteam-land.other-checkout", production / "bin/codeteam-land", fork / "teams/other-checkout.toml",
        "queue-run")
    job(agents, "com.codeteam.codeteam-recheck.acme", production / "bin/codeteam-land", production / "teams/acme.toml",
        "recheck-run")
    assert module.runner_jobs(fork, agents) == [(fork / "teams/sprocket.toml", "queue-run"),
                                                (fork / "teams/sprocket.toml", "validate-run")]
    assert module.runner_jobs(production, agents) == [(fork / "teams/other-checkout.toml", "queue-run"),
                                                      (production / "teams/acme.toml", "recheck-run")]


def test_the_program_matches_through_a_symlinked_checkout(tmp_path):
    real, agents = tmp_path / "real", tmp_path / "LaunchAgents"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    job(agents, "com.codeteam.codeteam-recheck.a", alias / "bin/codeteam-land", tmp_path / "a.toml", "recheck-run")
    assert module.runner_jobs(real, agents) == [(tmp_path / "a.toml", "recheck-run")]


def test_other_jobs_and_unreadable_files_are_not_runners(tmp_path):
    repo, agents = tmp_path / "repo", tmp_path / "LaunchAgents"
    job(agents, "com.codeteam.codeteam-buildq", repo / "bin/codeteam-buildq", tmp_path / "x.toml", "run")
    (agents / "com.codeteam.codeteam-land.short.plist").write_bytes(
        plistlib.dumps({"ProgramArguments": ["python3", str(repo / "bin/codeteam-land")]}))
    (agents / "com.codeteam.codeteam-land.broken.plist").write_text("not a plist")
    assert module.runner_jobs(repo, agents) == []
    assert module.runner_jobs(repo, tmp_path / "none") == []
