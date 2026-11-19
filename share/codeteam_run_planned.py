"""run_planned: zone-tool test-one runs its planned tests from the repo root and reports them (D526; moved unchanged
from cmd_test_one).

A "py" run is pytest over the path, a "script" run `<python> <path>`, anything else `bash <path>`. pytest's exit 5
(no tests collected) is not a failure and not a pass.
"""
import shlex
import subprocess
from pathlib import Path


def run_planned(runs: list[tuple[str, str]], pytest: list[str], py: str, root: Path, env: dict[str, str],
                target: str) -> int:
    """Run each (kind, path) in order, one ok or FAIL line each, then the totals; 1 if any failed, else 0 (also when
    nothing ran, after "no tests")."""
    passed, failed = 0, []
    for kind, rel in runs:
        cmd = {"py": [*pytest, rel], "script": [py, rel]}.get(kind, ["bash", rel])
        print(f"test-one: run {shlex.join(cmd)}", flush=True)
        rc = subprocess.run(cmd, cwd=root, env=env).returncode
        if kind == "py" and rc == 5:  # pytest collected nothing: no tests, not a failure
            continue
        if rc == 0:
            passed += 1
            print(f"ok   {rel}")
        else:
            failed.append(rel)
            print(f"FAIL {rel} (exit {rc})")
    if not passed and not failed:
        print(f"test-one: {target}: no tests")
        return 0
    print(f"test-one: {passed} passed, {len(failed)} failed" + (": " + " ".join(failed) if failed else ""))
    return 1 if failed else 0
