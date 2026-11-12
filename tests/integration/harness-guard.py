#!/usr/bin/env -S python3 -u
"""harness-guard: a team's own codeteam-land calls are never read as writes to the harness, even when a finding's
text quotes code with >, ; or |; real writes to the harness are still refused. The hook
runs as Claude Code runs it: a subprocess fed the tool call on stdin. Nothing outside a temp folder is written."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "share" / "claude-hooks" / "harness-guard.py"


def decide(command):
    """'deny' or 'allow' for a Bash command run by a team session, with codeteam's home at a temp folder."""
    with tempfile.TemporaryDirectory() as d:
        home = Path(d) / "codeteam"
        (home / "teams").mkdir(parents=True)
        manifest = home / "teams" / "acme.toml"
        manifest.write_text(f'product = "acme"\nworktree_root = "{Path(d) / "team-acme"}"\n')
        cmd = command.replace("{CT}", str(home)).replace("{M}", str(manifest))
        env = dict(os.environ, CODETEAM_MANIFEST=str(manifest), CODETEAM_HOME=str(home))
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": d}), capture_output=True, text=True,
            env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return "deny" if '"deny"' in r.stdout else "allow"


def test_a_finding_quoting_a_comparison_is_allowed():
    assert decide('{CT}/bin/codeteam-land {M} finding f --what "drop_seq > hook_seq is never checked"') == "allow"


def test_a_finding_quoting_separators_is_allowed():
    assert decide("{CT}/bin/codeteam-land {M} finding f --what 'a > b; rm x | tee y && z'") == "allow"


def test_reviewed_is_allowed():
    assert decide("{CT}/bin/codeteam-land {M} reviewed agent-a6fe02e0c938d7f8a") == "allow"


def test_a_redirect_into_the_harness_is_refused():
    assert decide("echo x > {CT}/bin/codeteam-land") == "deny"


def test_a_write_chained_after_codeteam_land_is_refused():
    assert decide("{CT}/bin/codeteam-land {M} queue; rm {CT}/teams/acme.toml") == "deny"


def test_a_redirect_after_2_and_1_on_codeteam_land_is_refused():
    assert decide("{CT}/bin/codeteam-land {M} queue 2>&1 > {CT}/teams/out.txt") == "deny"


def test_a_hash_inside_a_word_hides_no_later_write():
    assert decide("{CT}/bin/codeteam-land {M} finding x#y; rm {CT}/teams/acme.toml") == "deny"


def test_unbalanced_quotes_fall_back_to_the_old_split_and_still_refuse():
    assert decide('echo "x > {CT}/teams/acme.toml') == "deny"


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
