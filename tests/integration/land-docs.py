#!/usr/bin/env -S python3 -u
"""codeteam-land: the API delta (h), the docs pass after landing (a), file references (e) and docs-only landings.
A throwaway repo with one zone, A, holding Swift and Rust sources and a SPEC and INTERFACE."""
import contextlib
import importlib.machinery
import importlib.util
import io
import shlex
from unittest.mock import patch
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LAND = str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land")
W = Path(tempfile.mkdtemp(prefix="land-docs-"))
REPO, ROOT = W / "repo", W / "team"
TODAY = dt.date.today().isoformat()
fails = 0
loader = importlib.machinery.SourceFileLoader("cl_docs", LAND)
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
loader.exec_module(cl)


def sh(cmd, cwd=REPO, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"setup failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def land(*args, env=None):
    e = {k: v for k, v in os.environ.items() if k != "CODETEAM_SESSION"}
    # Keep home-scoped state inside the fixture, including logs from any stray land-check.
    e["HOME"] = str(W / "home")
    # That HOME has no .gitconfig, and git refuses even a conflicting merge without a committer identity.
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@t")):
        e.setdefault(k, v)
    e.update(env or {})
    result = subprocess.run([LAND, str(W / "team.toml"), *args], capture_output=True, text=True, env=e)
    if args[0] == "land" and result.returncode == 0:
        row = json.loads((ROOT / "land" / "reviews" / f"{args[1]}.json").read_text())
        for reviewer in row["reviewers"]:
            verdict = subprocess.run([LAND, str(W / "team.toml"), "reviewed", args[1]], capture_output=True, text=True,
                                     env=dict(e, CODETEAM_SESSION=reviewer))
            assert verdict.returncode == 0, verdict.stdout + verdict.stderr
    return result


def doc(version, body="Text."):
    return f"---\nversion: {version}\nstatus: active\ndate: 2026-01-01\ndescription: x\n---\n\n# Doc\n\n{body}\n\n## Changelog\n\n### {version} -- 2026-01-01\n\nOld entry.\n"


def wo(name, edits, msg=None):
    if sh("git rev-parse landing").stdout != sh("git rev-parse integration").stdout:
        promote(stamp=False)
    tree = Path(land("wo-cut", "A", name).stdout.strip())
    for path, text in edits.items():
        (tree / path).parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            (tree / path).unlink()
        else:
            (tree / path).write_text(text)
    (tree / ".msg").write_text(msg or name)
    sh("git add -A . ':!.msg' && git -c user.email=t@t -c user.name=l commit -q -F .msg && rm .msg", cwd=tree)
    r = land("land", name, *(["--doc-level", "minor"] if name == "flag" else []))
    return json.loads((ROOT / "land" / "wo" / f"{name}.json").read_text()), r


def front(path):
    text = sh(f"git show landing:{path}").stdout
    head = text.split("\n---", 1)[0]
    return {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in head.splitlines()[1:] if ":" in l)}, text


def run_queue(times=3):
    for _ in range(times):
        land("queue-run", "--once")


def promote(stamp=True):
    team = cl.Team(W / "team.toml")
    team.cfg["docs"]["enabled"] = stamp
    tip = sh("git rev-parse landing").stdout.strip()
    with (ROOT / "land" / "validation-results.jsonl").open("a") as file:
        file.write(json.dumps({"commit": tip, "result": "pass", "tests": []}) + "\n")
    output, errors = io.StringIO(), io.StringIO()
    # The code submits without waiting; the fixture drives the captured submission after Stage 7 returns.
    with patch.object(cl, "spawn") as started, contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        cl.stage7(team, tip)
    for call in started.call_args_list:
        command = shlex.split(call.args[0])
        if "land" in command and command[-1].startswith("docs-stamp-"):
            result = subprocess.run(command, capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
    return subprocess.CompletedProcess(["promote"], 0, output.getvalue(), errors.getvalue())


SWIFT = "public func open() {}\npublic func keep() {}\nfunc helper() {}\n"
RUST = "pub fn read() {}\npub struct Row;\n"
REPO.mkdir()
for path, text in {"A/Sources/a.swift": SWIFT, "A/Sources/b.swift": "public func other() {}\n",
                   "A/rust/src/lib.rs": RUST, "A/Package.swift": "// swift package\n",
                   "docs/reference/A_SPEC.md": doc("1.2.0"), "docs/reference/A_INTERFACE.md": doc("1.3.0"),
                   "A/docs/guide.md": doc("2.0.0"), "A/docs/third.md": doc("1.0.0"), "A/notes.md": "# Notes, ungoverned\n",
                   "B/Package.swift": '.package(path: "../A")\n'}.items():
    (REPO / path).parent.mkdir(parents=True, exist_ok=True)
    (REPO / path).write_text(text)
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init && git branch integration && git branch landing")
(W / "team.toml").write_text(f'''repo = "{REPO}"
integration = "integration"
worktree_root = "{ROOT}"
[[lanes]]
name = "A"
path = "A"
[[lanes]]
name = "B"
path = "B"
[land]
guard_ledger = "{W / 'ledger'}"
check = ""
test = "echo {{zone}} >> {W / 'gate.log'}"
gates = ""
seed_index = false
interface = false
codegraph = false
notify = "echo {{kind}} {{to}} {{text}} >> {W / 'notify.log'}"
owner_notify = "true"
[land.docs]
enabled = true
after = "git ls-files docs/reference > docs/tracked.txt"
''')
land("install-hook")
notes = lambda: (W / "notify.log").read_text() if (W / "notify.log").exists() else ""
gates = lambda: (W / "gate.log").read_text().count("A") if (W / "gate.log").exists() else 0

print("== the API delta (h)")
rec, _ = wo("rm", {"A/Sources/a.swift": "public func keep() {}\nfunc helper() {}\n"})
t("a removed public func is removed", any("open" in x for x in rec["api"]["removed"]), rec["api"])
rec, _ = wo("mv", {"A/Sources/a.swift": "public func open() {}\nfunc helper() {}\n",
                   "A/Sources/b.swift": "public func other() {}\npublic func keep() {}\n"})
t("a public func moved to another file of the zone is not removed", not rec["api"]["removed"] and not rec["api"]["added"], rec["api"])
rec, _ = wo("sig", {"A/rust/src/lib.rs": "pub fn read(limit: u32) {}\npub struct Row;\n"})
t("a changed signature is changed", any("read" in x for x in rec["api"]["changed"]), rec["api"])
rec, _ = wo("add", {"A/rust/src/lib.rs": "pub fn read() {}\npub struct Row;\npub fn write() {}\n"})
t("a new pub fn is added", any("write" in x for x in rec["api"]["added"]), rec["api"])
for x in ("mv", "sig", "add"):
    land("land-hold", x)

print("== after a landing: levels are recorded, the documents are not touched (2026-11-10)")
(ROOT / "workcrews" / "B").mkdir(parents=True, exist_ok=True)
pending = lambda: [json.loads(l) for l in (ROOT / "land" / "docs-pending.jsonl").read_text().splitlines()] \
    if (ROOT / "land" / "docs-pending.jsonl").exists() else []
level = lambda wo_, f: next((r["docs"].get(f) for r in pending() if r["wo"] == wo_), None)
SPEC, IFACE, GUIDE, OTHER = "docs/reference/A_SPEC.md", "docs/reference/A_INTERFACE.md", "A/docs/guide.md", "A/docs/other.md"
run_queue()
spec, spec_text = front(SPEC)
t("a removal records MAJOR for the zone's SPEC and INTERFACE", level("rm", SPEC) == "major" == level("rm", IFACE), pending())
t("the documents keep their versions, and no docs work order lands", spec.get("version") == "1.2.0"
  and front(IFACE)[0].get("version") == "1.3.0" and "docs-" not in sh("git log --format=%s integration").stdout, spec)
n0 = gates()
wo("guide", {GUIDE: doc("2.0.0", "Changed text, version left alone.")})
run_queue()
t("a governed doc changed without its bump records PATCH", level("guide", GUIDE) == "patch", pending())
t("a docs-only landing runs no build and no tests", gates() == n0, (n0, gates()))
wo("bumped", {GUIDE: doc("3.0.0", "Author bumped it.")})
run_queue()
t("a version the work order set by hand is left to it", level("bumped", GUIDE) == "hand", pending())
wo("plain", {"A/notes.md": "# Notes, ungoverned\nmore\n"})
run_queue()
t("an ungoverned doc records nothing", not any(r["wo"] == "plain" for r in pending()))
land("land-hold", "add")
run_queue()
t("an addition records MINOR for the zone's docs", level("add", IFACE) == "minor", pending())
_, iface_text = front(IFACE)
wo("ifaceonly", {IFACE: iface_text.replace("# Doc", "# Doc\n\nOne more line.", 1)}, msg="Interface: say what open returns")
run_queue()
t("an INTERFACE changed alone records the same level for SPEC and INTERFACE",
  level("ifaceonly", IFACE) == "patch" == level("ifaceonly", SPEC), pending())
wo("newdoc", {OTHER: doc("1.0.0")})
run_queue()
wo("stated", {GUIDE: doc("3.0.0", "Behaviour changed, declarations the same.")},
   msg="CLI: two refusals became skips\n\nDoc-Level: major")
run_queue()
wo("perpath", {OTHER: doc("1.0.0", "Other changed."), GUIDE: doc("3.0.0", "And the guide again.")},
   msg="Other and guide\n\nDoc-Level: patch\nDoc-Level: A/docs/other.md minor")
run_queue()
t("a Doc-Level line states the level for every governed doc the work order changed", level("stated", GUIDE) == "major", pending())
t("a Doc-Level line naming a document wins for it", level("perpath", OTHER) == "minor" and level("perpath", GUIDE) == "patch", pending())
wo("flag", {OTHER: doc("1.0.0", "Other changed again.")})
run_queue()
t("land --doc-level records the same", level("flag", OTHER) == "minor", pending())
wo("late", {"A/docs/third.md": doc("1.0.0", "Changed."), "A/docs/new-at-promote.md": doc("1.0.0")}, msg="Third: a late line\n\nDoc-Level: A/docs/third.md major")
run_queue()
pf = ROOT / "land" / "docs-pending.jsonl"
pf.write_text("".join(l + "\n" for l in pf.read_text().splitlines() if '"wo": "late"' not in l))

print("== at promote: one stamp")
(W / "ledger" / "changelog").mkdir(parents=True)
(W / "ledger" / "changelog" / "add.md").write_text("- 2026-11-10 — add: write() joins the public API.\n")
# A stamp is submitted from proven integration, lands separately, and reaches base at the next promote.
for _ in range(2):
    with (ROOT / "land" / "validation-results.jsonl").open("a") as f:
        f.write(json.dumps({"time": "now", "commit": sh("git rev-parse landing").stdout.strip(),
                            "result": "pass", "seconds": 1,
                            "tests": [{"name": "suite", "result": "pass", "seconds": 1}]}) + "\n")
    r = promote()
    run_queue()
t("promote stamps and promotes", r.returncode == 0 and "promoted" in r.stdout, r.stdout + r.stderr)
main = lambda f: sh(f"git show main:{f}").stdout
ver = lambda f: main(f).split("version: ", 1)[1].splitlines()[0]
t("SPEC and INTERFACE go to one MAJOR from the versions at the last promotion, once (1.2.0 and 1.3.0 -> 2.0.0)",
  ver(SPEC) == "2.0.0" == ver(IFACE), (ver(SPEC), ver(IFACE)))
t("their date is today", f"date: {TODAY}" in main(SPEC))
t("a stated MAJOR is applied to the version at the preceding promotion (3.0.0 -> 4.0.0)", ver(GUIDE) == "4.0.0", ver(GUIDE))
t("a level stated by a work order with no recorded row (landed before the tool) is honoured (1.0.0 -> 2.0.0)",
  ver("A/docs/third.md") == "2.0.0", ver("A/docs/third.md"))
t("a document that is new since the last promotion keeps the version it came with", ver("A/docs/new-at-promote.md") == "1.0.0", ver("A/docs/new-at-promote.md"))
log = main("docs/reference/A_CHANGELOG.md")
t("the zone's changelog file has one heading for the promotion with each work order's entry",
  log.count(f"## 2.0.0 -- {TODAY}") == 1 and "- ifaceonly: Interface: say what open returns" in log and "- rm: " in log, log[-600:])
t("the after step sees the changelog file the stamp creates (make public-docs copies tracked files only)",
  "docs/reference/A_CHANGELOG.md" in main("docs/tracked.txt"), main("docs/tracked.txt"))
t("the changelog header names no tool: it ships with the product",
  "Written at each promotion; never edited by hand." in log and "codeteam" not in log.split("## ", 1)[0], log[:300])
t("Kong's line is the entry when he has written one", "add: write() joins the public API." in log and "- add: add" not in log, log[-600:])
t("the documents keep no Changelog section; the old entries moved to the file",
  "## Changelog" not in main(SPEC) and "Earlier entries, moved from A_SPEC.md" in log and "Old entry." in log, main(SPEC)[-200:])
t("the stamp lands separately and a later promotion copies it to integration and main",
  sh("git log --first-parent --format=%s integration").stdout.count("docs-stamp-") == 1
  and sh("git rev-parse main").stdout == sh("git rev-parse integration").stdout)
t("nothing is left pending", pending() == [], pending())
r = promote()
t("a second promote with nothing owed makes no stamp", sh("git log --first-parent --format=%s integration").stdout.count("docs-stamp-") == 1, r.stdout + r.stderr)
wo("guide2", {GUIDE: main(GUIDE).replace("And the guide again.", "A later change.")})
run_queue()
for _ in range(2):
    with (ROOT / "land" / "validation-results.jsonl").open("a") as f:
        f.write(json.dumps({"time": "now", "commit": sh("git rev-parse landing").stdout.strip(),
                            "result": "pass", "seconds": 1,
                            "tests": [{"name": "suite", "result": "pass", "seconds": 1}]}) + "\n")
    promote()
    run_queue()
t("the next promotion bumps from the version at the last one (4.0.0 -> 4.0.1)", ver(GUIDE) == "4.0.1", ver(GUIDE))
dep = ROOT / "workcrews" / "B" / "ledger" / "reports" / "dependency-changes.md"
t("a zone that depends on the changed SPEC or INTERFACE and has no open work order gets a line in its ledger",
  dep.exists() and "A changed docs/reference/A_INTERFACE.md" in dep.read_text() and "ifaceonly" in dep.read_text(),
  dep.read_text() if dep.exists() else "no file")

print("== file references (e)")
wo("refs", {"A/notes.md": "# Notes, ungoverned\nSee a.swift and A/Sources/b.swift:400, and A/Sources/gone.swift:12.\n"})
run_queue()
line = next((l for l in reversed(notes().splitlines()) if "naming files that do not exist" in l), "")
n_notes = notes().count("naming files that do not exist")
wo("swiftnames", {"A/notes.md": "# Notes\n`AuditGate.contentID`, `Substrate.mutate` and `[package.metadata.acme-test]`.\n"})
run_queue()
t("Swift member names and a TOML table name are not read as missing files",
  notes().count("naming files that do not exist") == n_notes, notes()[-300:])
t("a missing file is reported to the zone; a file name, or a path with any line number, is enough",
  "gone.swift" in line and "b.swift" not in line and "a.swift" not in line.replace("gone.swift", ""), line)

print("== a Doc-Level declaration alone lands; a failed stamp says why and leaves its documents owed")
THIRD = "A/docs/third.md"
if sh("git rev-parse landing").stdout != sh("git rev-parse integration").stdout:
    promote(stamp=False)
n0 = gates()
trees = {name: Path(land("wo-cut", "A", name).stdout.strip()) for name in ("empty", "declare", "late2")}
third = trees["late2"] / THIRD
third.write_text(third.read_text().replace("Changed.", "Changed again."))
for name, body in (("empty", "Nothing at all"), ("declare", "Guide: its level\n\nDoc-Level: A/docs/guide.md minor"),
                   ("late2", "Third again\n\nDoc-Level: A/docs/third.md minor")):
    (trees[name] / ".msg").write_text(body)
    sh("git add -A . ':!.msg' && git -c user.email=t@t -c user.name=l commit --trailer 'Agent: repo-orchestrator' --trailer 'Model: claude-opus-5-5' --trailer 'Effort: xhigh' --trailer 'Worktree: main' -q --allow-empty -F .msg && rm .msg",
       cwd=trees[name])
r = land("land", "empty")
t("a work order with no change and no Doc-Level line is refused", r.returncode != 0 and "nothing to land" in r.stderr,
  r.stdout + r.stderr)
land("wo-retire", "empty", "--force")
r = land("land", "declare")
t("a work order whose only commit states a document's level lands", r.returncode == 0, r.stdout + r.stderr)
run_queue()
t("it runs no build and no tests", gates() == n0, (n0, gates()))
t("its level is recorded for the next stamp", level("declare", GUIDE) == "minor", pending())
land("land", "late2")
run_queue()
pf.write_text("".join(l + "\n" for l in pf.read_text().splitlines() if '"wo": "late2"' not in l))   # a late row
toml = (W / "team.toml").read_text()
(W / "team.toml").write_text(toml.replace('after = "git ls-files docs/reference > docs/tracked.txt"',
                                          'after = "echo names private docs path docs/RULINGS.md >&2; exit 3"'))
with (ROOT / "land" / "validation-results.jsonl").open("a") as f:
    f.write(json.dumps({"time": "now", "commit": sh("git rev-parse landing").stdout.strip(), "result": "pass",
                        "seconds": 1, "tests": [{"name": "suite", "result": "pass", "seconds": 1}]}) + "\n")
r = promote()
t("a failed after step stops the stamp and the report gives its exit and output",
  "Document stamp failed" in r.stderr and "exited 3" in r.stderr and "docs/RULINGS.md" in r.stderr, r.stderr[-600:])
# 2026-11-12: the refused line came from Kong's changelog entry file, which the report did not name.
t("the report names where each changelog entry came from",
  "late2 (its first commit subject)" in r.stderr and "Reword the one the refusal names" in r.stderr, r.stderr[-900:])
t("the promotion still happens", sh("git rev-parse main").stdout == sh("git rev-parse landing").stdout)
left = [p.name for p in (ROOT / "land" / "wo").glob("docs-stamp-*.json") if not p.name.endswith((".landed.json", ".retired.json"))]
t("the failed stamp's work order is retired, not left open", left == [], left)
t("its late row stays owed", level("late2", THIRD) == "minor" and level("declare", GUIDE) == "minor", pending())
(W / "team.toml").write_text(toml)
before = (ver(THIRD), ver(GUIDE))
wo("nudge", {"A/notes.md": "# Notes, ungoverned\nnudge\n"})
run_queue()
for _ in range(2):
    with (ROOT / "land" / "validation-results.jsonl").open("a") as f:
        f.write(json.dumps({"time": "now", "commit": sh("git rev-parse landing").stdout.strip(), "result": "pass",
                            "seconds": 1, "tests": [{"name": "suite", "result": "pass", "seconds": 1}]}) + "\n")
    promote()
    run_queue()
t("the next promotion stamps what the failed one owed", before == ("2.0.0", "4.0.1") and ver(THIRD) == "2.1.0"
  and ver(GUIDE) == "4.1.0", (before, ver(THIRD), ver(GUIDE)))
t("nothing is left pending after it", pending() == [], pending())

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
