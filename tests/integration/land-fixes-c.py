#!/usr/bin/env -S python3 -u
"""codeteam fixes, third set (2026-11-08): mail between teams goes to the other team's store; a zone test never sees
the session's CODETEAM_* settings. Throwaway folders only."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HOME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOME / "v2"))
from codeteam2 import cli  # noqa: E402

W = Path(tempfile.mkdtemp(prefix="land-fixes-c-"))
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


print("== mail to another team")
for n in ("widgets", "codeteam", "acme"):
    (W / f"{n}.toml").write_text(f'product = "{n}"\n')
tess = SimpleNamespace(product="widgets", manifest=str(W / "widgets.toml"))
t("a REQUEST to codeteam from a product team goes to codeteam's store",
  cli.other_team(tess, "codeteam", "REQUEST") == W / "codeteam.toml")
t("Orc-Codeteam, any kind, goes there too", cli.other_team(tess, "Orc-Codeteam", "NOTE") == W / "codeteam.toml")
t("an ANSWER to codeteam (an idle check) stays here", cli.other_team(tess, "codeteam", "ANSWER") is None)
t("Orc-Acme from widgets goes to acme's store", cli.other_team(tess, "Orc-Acme", "ANSWER") == W / "acme.toml")
t("a team's own orchestrator is not another team", cli.other_team(tess, "Orc-Widgets", "NOTE") is None)
t("a team with no manifest is not forwarded", cli.other_team(tess, "Orc-Nobody", "NOTE") is None)
ct = SimpleNamespace(product="codeteam", manifest=str(W / "codeteam.toml"))
t("codeteam answering Orc-Widgets reaches widgets' store", cli.other_team(ct, "Orc-Widgets", "ANSWER") == W / "widgets.toml")

print("== a zone test never sees the session's team settings")
R = W / "repo"
(R / "tests").mkdir(parents=True)
(R / "tests" / "t.sh").write_text('[ -z "$CODETEAM_MANIFEST" ] && [ -z "$CODETEAM_SESSION" ] && [ -z "$HERDR_SESSION" ] '
                                   '&& [ -n "$CODETEAM_HOME" ]\n')
subprocess.run("git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm i", shell=True, cwd=R)
env = dict(os.environ, CODETEAM_MANIFEST="/live/team.toml", CODETEAM_SESSION="Orc-Live", HERDR_SESSION="codeteam",
           CODETEAM_HOME=str(HOME))
r = subprocess.run([str(HOME / "bin" / "zone-tool"), "test-one", "tests"], cwd=R, env=env, capture_output=True, text=True)
t("CODETEAM_MANIFEST, CODETEAM_SESSION and HERDR_SESSION are dropped; CODETEAM_HOME stays", r.returncode == 0,
  r.stdout[-400:] + r.stderr[-400:])

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
