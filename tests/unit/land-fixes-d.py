#!/usr/bin/env -S python3 -u
"""codeteam fixes, fourth set (2026-11-08, from the messages Orc-Codeteam sent the creator): walls ask about the
landing's own zone; a step whose zone-test records all passed passes; a duplicate ruling number fails the gate; the
union-log block keeps a team's own rules (mail for the creator reaching its inbox is v2/tests/test_for_creator.py).
Throwaway folders only. A unit test script (rule 11): each check calls one codeteam-land function on values or on fixture files it
writes in its temp folder, and codeteam-land's import-time launchctl call is faked."""
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HOME = Path(__file__).resolve().parents[2]
ld = importlib.machinery.SourceFileLoader("cl", str(HOME / "bin" / "codeteam-land"))
sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    ld.exec_module(cl)

W = Path(tempfile.mkdtemp(prefix="land-fixes-d-"))
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


print("== walls ask about the landing's own zone")
team = SimpleNamespace(zones={"data": ["."], "training": ["."], "A": ["pkg/A"]})
t("a file in two whole-repo zones is inside the second one too", cl.in_zone(team, "x.py", "training"))
t("a file outside a path zone is outside it", not cl.in_zone(team, "x.py", "A"))

print("== a step whose zone-test records all passed passes")
rec = W / ".test-record-1.json"
rec.write_text(json.dumps({"result": "PASS"}))
out = f"lines\nzone-test: PASS (exit 0); record {rec}\n"
t("named PASS records count as a pass", cl.records_pass(out))
rec.write_text(json.dumps({"result": "FAIL"}))
t("a record that says FAIL does not", not cl.records_pass(out))
t("output naming no record does not", not cl.records_pass("FAIL something\n"))
rec.write_text(json.dumps({"result": "PASS"}))
t("a step with any output after its last record does not",
  not cl.records_pass(out + "some later command's silent output\n"))
t("a step that failed after its last record does not",
  not cl.records_pass(out + "make: *** [zone-test-one] Error 2\n"))

print("== a duplicate ruling number fails the gate")
(W / "docs").mkdir()
(W / "docs" / "RULINGS.md").write_text("# Rulings\n\n## R-1. one\n\n## R-2. two\n\nSee R-1. for that.\n")
t("distinct numbers pass", cl.duplicate_rulings(W) == [], cl.duplicate_rulings(W))
(W / "docs" / "RULINGS.md").write_text("# Rulings\n\n## R-1. one\n\n## R-2. two\n\n## R-2. again\n")
t("a number used twice is named", any("R-2" in x for x in cl.duplicate_rulings(W)), cl.duplicate_rulings(W))
(W / "docs" / "RULINGS.md").write_text("## R-1. one\n")
(W / "v2").mkdir()
(W / "v2" / "DECISIONS.md").write_text("248. **a** x\n249. **b** y\n249. **c** z\n")
t("a decision number used twice is named", any(x.startswith("249") for x in cl.duplicate_rulings(W)),
  cl.duplicate_rulings(W))
(W / "v2" / "DECISIONS.md").write_text("248. **a** x\n")

print("== the union-log block keeps a team's own rules")
common = W / "git"
(common / "info").mkdir(parents=True)
(common / "info" / "attributes").write_text("*.png binary\n")
cl.install_union_logs(common)
f = common / "info" / "attributes"
f.write_text(f.read_text() + "NOTES.md merge=union\n")
cl.install_union_logs(common)
txt = f.read_text()
t("a team's own union rule after codeteam's block stays", "NOTES.md merge=union" in txt and "*.png binary" in txt, txt)
t("codeteam's block is written once, without RULINGS.md", txt.count("DECISIONS.md merge=union") == 1
  and "RULINGS.md" not in txt, txt)

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
