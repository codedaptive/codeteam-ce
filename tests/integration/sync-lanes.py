#!/usr/bin/env -S python3 -u
"""The sync-lanes CLI refreshes an existing scratch team's lane records."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODETEAM = ROOT / "bin" / "codeteam"


def scratch_team(root):
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "README").write_text("readme\n")
    (repo / "bolt").mkdir()
    (repo / "bolt" / "test.txt").write_text("bolt\n")
    subprocess.run(["git", "-C", str(repo), "add", "README", "bolt"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-q", "-m", "initial"], check=True)
    home = root / "scratch-team"
    (home / "team").mkdir(parents=True)
    manifest = root / "sample.toml"
    manifest.write_text(f'product = "sample"\nrepo = "{repo}"\nbase = "main"\n'
                        f'worktree_root = "{home}"\n'
                        '[[lanes]]\nname = "tooling"\npath = "."\n'
                        'owns = ["README"]\n')
    team_file = home / "team" / "team.json"
    team_file.write_text(json.dumps({"lanes": {
        "tooling": {"path": ".", "owns": ["old"]},
        "retained": {"path": "legacy", "owns": ["untouched"], "job": "keep"}}}))
    return manifest, team_file


def invoke(manifest):
    return subprocess.run([sys.executable, str(CODETEAM), "sync-lanes", str(manifest)],
                          capture_output=True, text=True)


def test_sync_lanes_updates_existing_lane_without_removing_unmatched_lane():
    with tempfile.TemporaryDirectory() as tmp:
        manifest, team_file = scratch_team(Path(tmp))
        manifest.write_text(manifest.read_text().replace('owns = ["README"]', 'owns = ["README", "bolt"]'))
        result = invoke(manifest)
        assert result.returncode == 0, f"sync-lanes exited {result.returncode}: {result.stderr.strip()}"
        lanes = json.loads(team_file.read_text())["lanes"]
        assert lanes["tooling"]["owns"] == ["README", "bolt"]
        assert lanes["retained"] == {"path": "legacy", "owns": ["untouched"], "job": "keep"}
        assert set(lanes) == {"tooling", "retained"}


def test_sync_lanes_discovery_failure_names_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        manifest, team_file = scratch_team(Path(tmp))
        with manifest.open("a") as stream:
            stream.write('[[lanes]]\nname = "tooling"\npath = "bolt"\n')
        before = team_file.read_text()
        result = invoke(manifest)
        assert result.returncode != 0
        assert str(manifest) in result.stderr, f"discovery failure did not name manifest: {result.stderr.strip()}"
        assert team_file.read_text() == before


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except (Exception, SystemExit) as exc:
                failed += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)
