#!/usr/bin/env -S python3 -u
"""The status bar shows exactly the questions the user owes an answer to: codeteam-question is the
one way in and out of questions.md, and codeteam-statusline counts only its lines. A throwaway team folder."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
W = Path(tempfile.mkdtemp(prefix="question-tool-"))
(W / "team" / "team").mkdir(parents=True)
(W / "t.toml").write_text(f'repo = "{W}"\nworktree_root = "{W / "team"}"\n[[assistants]]\nname = "Designer-X"\nrole = "designer"\n')
QF = W / "team" / "team" / "questions.md"
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def q(*args, me="Designer-X"):
    return subprocess.run([str(BIN / "codeteam-question"), str(W / "t.toml"), *args], capture_output=True, text=True,
                          env=dict(os.environ, CODETEAM_SESSION=me))


def bar():
    r = subprocess.run([str(BIN / "codeteam-statusline"), str(QF)], input="{}", capture_output=True, text=True,
                       env=dict(os.environ, CLAUDE_PROJECT_DIR=str(W)))
    return r.stdout.strip()


ASK = ("ask", "--id", "Q-1", "--problem", "The disk is at 90%. Delete the old build folders?",
       "--option", "delete them", "--option", "leave them", "--pick", "delete them")
r = q(*ASK)
t("a designer asks a question: problem, options, pick", r.returncode == 0 and "status bar now shows 1" in r.stdout, r.stderr)
t("the status bar shows 1", "Questions: 1" in bar() and "not in question form" not in bar(), bar())
t("the same id twice is refused", q(*ASK).returncode == 2)
t("one option is refused", q("ask", "--id", "Q-2", "--problem", "x?", "--option", "a", "--pick", "a").returncode == 2)
t("a problem that is not a question is refused",
  q("ask", "--id", "Q-2", "--problem", "the disk is full", "--option", "a", "--option", "b", "--pick", "a").returncode == 2)
t("a wall of text is refused",
  q("ask", "--id", "Q-2", "--problem", "x " * 300 + "?", "--option", "a", "--option", "b", "--pick", "a").returncode == 2)
t("the orchestrator does not write the file in a team with a designer", q(*ASK[:2], "Q-3", *ASK[3:], me="orc").returncode == 2)
with open(QF, "a") as f:
    f.write("- NOTICE: 3 folders are safe to delete, 1.2 GB\n- Q-OLD: WAITING, not for the owner yet\n")
t("lines written by hand are not counted, and are shown as not in form",
  "Questions: 1 (+2 not in question form)" in bar(), bar())
r = q("check")
t("check names them", r.returncode == 1 and "NOTICE" in r.stdout and "1 in form, 2 not" in r.stdout, r.stdout)
r = q("answered", "Q-1", "delete them")
t("answered takes the line out and keeps it in questions-closed.md", r.returncode == 0 and "Q-1 |" not in QF.read_text()
  and "answered: delete them" in (QF.parent / "questions-closed.md").read_text(), r.stderr)
t("the status bar shows 0 questions and still the two stray lines", "Questions: 0 (+2 not in question form)" in bar(), bar())
QF.write_text("# Open questions for the user\n")
t("an empty file shows no Questions field", "Questions" not in bar(), bar())
q(*ASK[:2], "Q-4", *ASK[3:])
r = q("withdraw", "Q-4", "--reason", "the disk has room again")
t("withdraw takes a question out with its reason", r.returncode == 0 and "Questions" not in bar()
  and "withdrawn: the disk has room again" in (QF.parent / "questions-closed.md").read_text(), r.stderr)
t("a closed id cannot be reused", q(*ASK[:2], "Q-4", *ASK[3:]).returncode == 2)
print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
