#!/usr/bin/env -S python3 -u
"""A repo that tracks its own .claude/skills (a fork of an upstream project) still gets the team's skills, linked by name and kept
out of git (2026-11-09). A throwaway repo."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
LAND = str(HOME / "bin" / "codeteam-land")
ld = importlib.machinery.SourceFileLoader("cl", LAND)
sp = importlib.util.spec_from_loader("cl", ld)
cl = importlib.util.module_from_spec(sp)
ld.exec_module(cl)
W = Path(tempfile.mkdtemp(prefix="team-skills-"))
REPO, ROOT = W / "repo", W / "team"
fails = 0


def t(label, cond, detail=""):
    global fails
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else f"  [{detail}]"))
    fails += not cond


def sh(cmd, cwd=REPO):
    return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)


(REPO / ".claude" / "skills" / "up1").mkdir(parents=True)
(REPO / ".claude" / "skills" / "up1" / "SKILL.md").write_text("upstream\n")
(REPO / "A").mkdir()
(REPO / "A" / "x").write_text("1\n")
sh("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm i && git branch integration")
skills = ROOT / "team" / "claude" / "skills"
for n in ("up1", "refocus", "zone-tests"):
    (skills / n).mkdir(parents=True)
    (skills / n / "SKILL.md").write_text(n + "\n")
(W / "team.toml").write_text(f'repo = "{REPO}"\nintegration = "integration"\nworktree_root = "{ROOT}"\n'
                             '[[lanes]]\nname = "A"\npath = "A"\n[land]\ncheck = ""\ngates = ""\nnotify = "true"\n')
e = {k: v for k, v in os.environ.items() if not k.startswith("CODETEAM_")}
tree = Path(subprocess.run([LAND, str(W / "team.toml"), "wo-cut", "A", "w1"], capture_output=True, text=True,
                           env=e).stdout.strip())
d = tree / ".claude" / "skills"
print("== a work order tree")
t("each team skill is linked in by name", (d / "refocus").is_symlink() and (d / "zone-tests").is_symlink())
t("the repo's own skill of the same name is left alone", (d / "up1").is_dir() and not (d / "up1").is_symlink())
t("git sees nothing new", sh("git status --porcelain", cwd=tree).stdout == "", sh("git status --porcelain", cwd=tree).stdout)
t("git add -A stages nothing", sh("git add -A --dry-run", cwd=tree).stdout == "")

print("== a checkout whose .claude/.gitignore un-ignores skills/**")
(REPO / ".claude" / ".gitignore").write_text("*\n!skills/\n!skills/**\n")
linked, refused = cl.link_team_skills(REPO, skills)
t("the links git would show are removed, and named", linked == [] and set(refused) == {"refocus", "zone-tests"}
  and not (REPO / ".claude" / "skills" / "refocus").exists(), (linked, refused))
t("and git still sees nothing new", sh("git status --porcelain").stdout == "", sh("git status --porcelain").stdout)
(REPO / ".claude" / ".gitignore").write_text("*\n!skills/\nskills/*\n!skills/up1/\n!skills/up1/**\n")
linked, refused = cl.link_team_skills(REPO, skills)
t("with upstream's own skills un-ignored by name, they link", set(linked) == {"refocus", "zone-tests"} and not refused,
  (linked, refused))
t("still clean", sh("git status --porcelain").stdout == "", sh("git status --porcelain").stdout)
t("a second run links nothing more", cl.link_team_skills(REPO, skills) == ([], []))
ex = Path(sh("git rev-parse --git-common-dir").stdout.strip())
ex = (REPO / ex if not ex.is_absolute() else ex) / "info" / "exclude"
t("the exclude lines are written once", ex.read_text().count("/.claude/skills/refocus\n") == 1, ex.read_text())

print("== one helper")
src = lambda f: (lambda s: s[s.index("SKILLS_MARK = "):s.index("    return linked, refused\n", s.index("def link_team_skills"))])(
    (HOME / "bin" / f).read_text())
t("link_team_skills is the same text in codeteam and codeteam-land", src("codeteam") == src("codeteam-land"))

print(f"\n{'all passed' if not fails else f'{fails} failed'}  ({W})")
sys.exit(1 if fails else 0)
