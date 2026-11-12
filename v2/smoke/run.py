#!/usr/bin/env python3
"""A repeatable codeteam v2 smoke run (phase 6): a fresh made-up project, a fresh team, one task,
checked end to end. Never touches a real repo or team.

    python3 v2/smoke/run.py [--name smokerun] [--keep] [--timeout 1200]

1. Makes $CODETEAM_WORKSPACE/sandbox/<name>-project (two zones whose specs are ahead of the code) and a local
   bare repo as its origin; writes v2/teams/<name>.toml (lab mode, lane cap 1, Haiku lanes).
2. codeteam v1 `init` (worktrees, roles), then `codeteam2 up` (herdr workspace, Orc, the loop).
3. Sends the orchestrator smoke task 1 as Owner, and waits for its DONE (or ANSWER) to Owner.
4. Checks: the full test suite passes on main, main has new commits, every message was delivered.
5. Prints PASS or FAIL with the evidence; `--keep` leaves the team running, else `codeteam2 down --close`.
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

V2 = Path(__file__).resolve().parent.parent
CT = V2.parent
SANDBOX = Path(os.environ.get("CODETEAM_WORKSPACE") or Path.home() / "codeteam-work") / "sandbox"
ENV = dict(os.environ, PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + os.environ.get("PATH", ""))

FILES = {
    "README.md": "# smoke project\n\nA made-up repo for codeteam v2 smoke runs. Zones: zones/alpha, zones/beta.\n",
    "Makefile": textwrap.dedent("""\
        .PHONY: help test test-one
        help:
        \t@echo "make test | make test-one DIR=<zone>"
        test:
        \t@python3 -m unittest discover -s zones -t . -p 'test_*.py'
        test-one:
        \t@test -n "$(DIR)" || { echo "test-one: set DIR"; exit 2; }
        \t@python3 -m unittest discover -s $(DIR) -t . -p 'test_*.py'
        """),
    ".gitignore": "__pycache__/\n*.pyc\n",
    "zones/__init__.py": "", "zones/alpha/__init__.py": "", "zones/beta/__init__.py": "",
    "zones/alpha/calc.py": textwrap.dedent('''\
        """Arithmetic helpers (ALPHA_SPEC.md)."""


        def add(a, b):
            """Return a + b."""
            return a + b


        def mean(values):
            """Return the arithmetic mean of a non-empty list of numbers."""
            return sum(values) / len(values)
        '''),
    "zones/alpha/test_calc.py": textwrap.dedent('''\
        import unittest
        from zones.alpha import calc


        class CalcTests(unittest.TestCase):
            def test_add(self):
                self.assertEqual(calc.add(2, 3), 5)

            def test_mean(self):
                self.assertEqual(calc.mean([1, 2, 3]), 2)
        '''),
    "zones/beta/report.py": textwrap.dedent('''\
        """Reports over numbers (BETA_SPEC.md)."""
        from zones.alpha import calc


        def summary(values):
            """One line: count and mean."""
            return f"{len(values)} values, mean {calc.mean(values):g}"
        '''),
    "zones/beta/test_report.py": textwrap.dedent('''\
        import unittest
        from zones.beta import report


        class ReportTests(unittest.TestCase):
            def test_summary(self):
                self.assertEqual(report.summary([2, 4]), "2 values, mean 3")
        '''),
    "docs/reference/ALPHA_SPEC.md": textwrap.dedent("""\
        # ALPHA SPEC

        1. `add(a, b)` returns a + b.
        2. `mean(values)` returns the arithmetic mean. For an empty list it raises `ValueError("mean of no values")`.
        3. `median(values)` returns the middle value of the sorted list; for an even count, the mean of the two middle values. For an empty list it raises `ValueError("median of no values")`.
        """),
    "docs/reference/BETA_SPEC.md": textwrap.dedent("""\
        # BETA SPEC

        1. `summary(values)` returns `"<n> values, mean <m>"` with `<m>` formatted by `:g`.
        2. For an empty list, `summary` returns `"no values"` (it never raises).
        3. `summary` also reports the median once alpha provides it: `"<n> values, mean <m>, median <d>"`.
        """),
}

TASK = ("Smoke task 1. The specs in docs/reference are ahead of the code. Get the code to match them, through the "
        "zone lanes: alpha implements ALPHA_SPEC items 2 and 3 with tests; beta implements BETA_SPEC items 2 and 3 "
        "with tests. beta's item 3 needs alpha's median, so alpha's work lands first. Each lane pushes its work up "
        "when its zone tests pass. Report DONE to Owner, with the commits on main, when both have landed.")


def sh(*args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, env=ENV, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"FAILED: {' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}")
    return r.stdout


FACTORY_TOP = 'builder = "Nagatha"\nguard = "Kong"\nguard_per = "feature"\n'
FACTORY = textwrap.dedent("""\

    [[assistants]]
    name = "Kong"
    agent = "kong-opus-5-5-medium"
    job = "Guard and auditor: reviews each feature pushed to exchange against the specs"
    tier = "exchange"
    permission_mode = "bypassPermissions"

    [[assistants]]
    name = "Nagatha"
    agent = "nagatha-opus-5-5-medium"
    job = "Builder: puts integration in order, runs the whole suite, promotes to main"
    tier = "integration"
    permission_mode = "bypassPermissions"
    """)


def manifest(name, project, root, factory=False, session="codeteam"):
    head = textwrap.dedent(f"""\
        # codeteam v2 smoke run (written by v2/smoke/run.py): sandbox only.
        product = "{name}"
        mode = "{'factory' if factory else 'lab'}"
        repo = "{project}"
        base = "main"
        lane_branch_prefix = "lane/"
        worktree_root = "{root}"
        claude_source = "{V2 / 'smoke' / ('claude-fab' if factory else 'claude')}"
        """)
    # TOML: every top-level key before the first table; the assistants' tables go last.
    return head + (FACTORY_TOP if factory else "") + _rest(name, session) + (FACTORY if factory else "")


def _rest(name, session="codeteam"):
    return textwrap.dedent(f"""\
        orc_agent = ""
        lane_agent = ""
        lane_coder = ""
        model = "claude-sonnet-5-5"
        lane_model = "claude-haiku-5-5"
        effort = "medium"
        lane_effort = "low"
        lane_permission_mode = "bypassPermissions"
        orc_permission_mode = "bypassPermissions"
        compact_window = 200000
        orc_compact_window = 200000

        [env]
        ZONE_TEST = "make --no-print-directory test-one DIR=$(ZONE)"
        ZONE_TEST_FLAGS = "--single --timeout 600"

        [v2]
        herdr_session = "{session}"
        cap = 1
        swap_idle_min = 1
        blocked_alert_min = 1
        agent = ""
        mcp = false

        [[lanes]]
        name = "alpha"
        path = "zones/alpha"
        role = "zone"

        [[lanes]]
        name = "beta"
        path = "zones/beta"
        role = "zone"
        """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="smokerun")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--herdr-session", default="codeteam",
                    help="the herdr session the team runs in (a separate one keeps a test away from real teams)")
    ap.add_argument("--factory", action="store_true",
                    help="exchange -> integration -> main, with Kong reviewing and Nagatha promoting")
    a = ap.parse_args()
    name = a.name.lower()
    if name in ("smoke",) or not name.isalnum():
        raise SystemExit("pick another --name (letters and digits; not an existing team)")
    project, origin, root = SANDBOX / f"{name}-project", SANDBOX / f"{name}-origin.git", SANDBOX / f"team-{name}"
    mpath = V2 / "teams" / f"{name}.toml"
    c2 = str(V2 / "bin" / "codeteam2")
    t0 = time.time()

    # 0. A previous run of this name: take it down and remove it (sandbox paths only).
    if mpath.exists():
        subprocess.run([c2, "down", str(mpath), "--close"], env=ENV, capture_output=True)
        time.sleep(3)
    for p in (project, origin, root):
        if p.exists():
            assert str(p).startswith(str(SANDBOX) + "/"), p
            shutil.rmtree(p)

    # 1. The project.
    sh("git", "init", "-q", "--bare", "-b", "main", str(origin))
    project.mkdir(parents=True)
    sh("git", "init", "-q", "-b", "main", cwd=project)
    for rel, body in FILES.items():
        f = project / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    sh("git", "add", "-A", cwd=project)
    sh("git", "-c", "user.email=smoke@local", "-c", "user.name=smoke", "commit", "-qm", "smoke project", cwd=project)
    sh("git", "remote", "add", "origin", str(origin), cwd=project)
    sh("git", "push", "-q", "origin", "main", cwd=project)
    base_commit = sh("git", "rev-parse", "HEAD", cwd=project).strip()
    mpath.write_text(manifest(name, project, root, a.factory, a.herdr_session))

    # 2. The team.
    sh(str(CT / "bin" / "codeteam"), "init", str(mpath), "--all-lanes")
    print(sh(c2, "up", str(mpath)).strip().splitlines()[-1])
    db = root / "team" / "v2" / "messages.db"

    # 3. The task.
    task = TASK + (" This team runs the full flow: lanes push up to exchange, Kong reviews each feature, you integrate "
                   "exchange with READY from every decider, and Nagatha promotes integration to main. Report DONE "
                   "to Owner only once the work is on main." if a.factory else "")
    sh(c2, "say", str(mpath), "general", "Owner", "REQUEST", f"Orc-{name.capitalize()}", task)
    print(f"task sent; waiting up to {a.timeout}s for the orchestrator's report to Owner ...", flush=True)
    done = None
    while time.time() - t0 < a.timeout:
        time.sleep(10)
        con = sqlite3.connect(str(db))
        # The orchestrator's own report: another session's answer to Owner (Kong's review verdict) is not it.
        row = con.execute("SELECT id, kind, body FROM messages WHERE target='user' AND kind IN ('DONE','ANSWER') "
                          "AND sender LIKE 'Orc-%' ORDER BY id DESC LIMIT 1").fetchone()
        con.close()
        if row:
            done = row
            break

    # 4. Checks.
    checks = []
    checks.append(("the orchestrator reported to Owner", bool(done), f"#{done[0]} {done[1]}: {done[2][:160]}" if done else "no report"))
    tests = subprocess.run(["make", "test"], cwd=project, env=ENV, capture_output=True, text=True)
    out = (tests.stdout + tests.stderr).strip().splitlines()
    checks.append(("the full suite passes on main", tests.returncode == 0, out[-3:] if out else []))
    log = sh("git", "log", "--oneline", f"{base_commit}..main", cwd=project).strip().splitlines()
    checks.append(("main has the work", len(log) >= (1 if a.factory else 2), log))   # a promote squashes into one
    con = sqlite3.connect(str(db))
    left = con.execute("SELECT COUNT(*) FROM messages WHERE state IN ('queued','held')").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM messages WHERE kind != 'RUNTIME'").fetchone()[0]
    con.close()
    info = f"{left} of {total} messages still waiting (duplicates from channel reading, RESULTS finding 10, can leave a few)"
    print(f"\ncodeteam v2 smoke run '{name}': {int(time.time() - t0)}s")
    for what, ok, ev in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}: {ev}")
    print(f"  INFO  {info}")
    if not a.keep:
        subprocess.run([c2, "down", str(mpath), "--close"], env=ENV, capture_output=True)
    ok = all(c[1] for c in checks)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
