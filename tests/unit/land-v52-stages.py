#!/usr/bin/env -S python3 -u
"""Unit contracts for the v5.2 landing decisions."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HOME = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl", loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)

W = Path(tempfile.mkdtemp(prefix="land-v52-stages-"))
(W / "repo").mkdir()
(W / "team.toml").write_text(f'repo = "{W / "repo"}"\nworktree_root = "{W / "root"}"\n'
                             f'[env]\nTMPDIR = "{W}"\n')
(W / "configured.toml").write_text(f'repo = "{W / "repo"}"\nworktree_root = "{W / "root"}"\n'
                                   f'[env]\nTMPDIR = "{W}"\n[land]\nhang_min = 7\nhang_cpu_pct = 3\n')
team = cl.Team(str(W / "team.toml"))
configured = cl.Team(str(W / "configured.toml"))
failed = 0


def t(label, cond, detail):
    global failed
    print(f"  {'PASS' if cond else 'FAIL'} {label}" + (f" {detail}" if not cond else ""))
    failed += not cond


def case(label, fn, expected):
    try:
        actual = fn()
        t(label, actual == expected, f"expected {expected!r}, got {actual!r}")
    except Exception as exc:
        t(label, False, f"{type(exc).__name__}: {exc}")


def env_for(team, group):
    with patch.dict(os.environ, {}, clear=True):
        return cl.team_env(team, group)


def outcome(rc, text, records):
    with patch.object(cl, "records_pass", return_value=records):
        return cl.step_outcome(rc, text)


case("hang defaults", lambda: cl.hang_settings({}), {"CODETEAM_HANG_WINDOW": "600", "CODETEAM_HANG_CPU_PCT": "1"})
case("hang overrides stringify", lambda: cl.hang_settings({"hang_min": 7, "hang_cpu_pct": 3}),
     {"CODETEAM_HANG_WINDOW": "420", "CODETEAM_HANG_CPU_PCT": "3"})
case("unit environment hang defaults", lambda: {k: env_for(team, "unit").get(k) for k in ("CODETEAM_HANG_WINDOW", "CODETEAM_HANG_CPU_PCT")},
     {"CODETEAM_HANG_WINDOW": "600", "CODETEAM_HANG_CPU_PCT": "1"})
case("integration environment hang overrides", lambda: {k: env_for(configured, "integration").get(k) for k in ("CODETEAM_HANG_WINDOW", "CODETEAM_HANG_CPU_PCT")},
     {"CODETEAM_HANG_WINDOW": "420", "CODETEAM_HANG_CPU_PCT": "3"})
case("integration environment group keys", lambda: {k: env_for(team, "integration").get(k) for k in ("GROUP", "CODETEAM_TEST_GROUP")},
     {"GROUP": "integration", "CODETEAM_TEST_GROUP": "integration"})

case("step success", lambda: outcome(0, "ok", False), "PASS")
case("step failure", lambda: outcome(1, "bad", False), "FAIL")
case("step nonzero passing records", lambda: outcome(1, "records", True), "PASS")
case("hung overrides success", lambda: outcome(0, "before\n  zone-test: HUNG  \nafter", True), "HUNG")
case("hung overrides failure", lambda: outcome(1, "zone-test: HUNG", False), "HUNG")
case("hung marker must be a whole line", lambda: outcome(0, "prefix zone-test: HUNG suffix", False), "PASS")

zones = {"a": ["src/a", "shared"], "b": ["src/b"], "all": ["."]}
case("touches nested zone folder", lambda: cl.touches_zone(zones, ["src/a/f.py"], "a"), True)
case("touches exact zone folder", lambda: cl.touches_zone(zones, ["shared"], "a"), True)
case("touches rejects prefix sibling", lambda: cl.touches_zone(zones, ["src/ab/f.py"], "a"), False)
case("touches dot covers everything", lambda: cl.touches_zone(zones, ["outside/f.py"], "all"), True)
case("touches unknown zone", lambda: cl.touches_zone(zones, ["src/a/f.py"], "missing"), False)
case("docs only nonempty", lambda: cl.docs_only(["a.md", "guide.txt"], [".md", ".txt"]), True)
case("docs only mixed files", lambda: cl.docs_only(["a.md", "src/a.py"], [".md", ".txt"]), False)
case("docs only empty files", lambda: cl.docs_only([], [".md"]), False)
case("queue entry", lambda: cl.queue_entry("wo-2", "tip123", "base456", ["z", "a"], "now"),
     {"wos": ["wo-2"], "wo": "wo-2", "tip": "tip123", "base": "base456", "zones": ["a", "z"],
      "queued": "now", "state": "waiting", "review": "pending"})
case("landing message", lambda: cl.landing_message("wo-2", "a", "one\ntwo"),
     "wo-2 (a)\n\none\ntwo\n\nWork-Order: wo-2\nZone: a\nLanded-By: codeteam land-one\n")

landings = [("first", ["src/a/readme.md"]), ("second", ["src/b/x.py"]),
            ("third", ["src/a/x.py"]), ("second", ["src/b/y.py"]), ("fourth", ["src/a/z.py"])]
case("overlap ignores docs preserves order and deduplicates", lambda: cl.overlapping(zones, landings, ["a", "b"], [".md"]),
     ["second", "third", "fourth"])
case("overlap ignores untested zone", lambda: cl.overlapping(zones, [("b-only", ["src/b/x.py"])], ["a"], [".md"]), [])
case("overlap dot covers all non-doc files", lambda: cl.overlapping(zones, [("doc", ["else/a.md"]),
     ("code", ["else/a.py"])], ["all"], [".md"]), ["code"])
case("recheck row", lambda: cl.recheck_row("merge123", "wo-2", ("wo-1", "wo-0"), ["z", "a"], "now"),
     {"time": "now", "M": "merge123", "wo": "wo-2", "overlapping": ["wo-1", "wo-0"], "zones": ["a", "z"]})
case("warm source absent", lambda: cl.warm_source(W / "cold"), None)
(W / "warm" / "land" / "itest").mkdir(parents=True)
case("warm source present", lambda: cl.warm_source(W / "warm"), W / "warm" / "land" / "itest")

print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
