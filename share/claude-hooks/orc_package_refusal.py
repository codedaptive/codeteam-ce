"""Why the orchestrator may not write a path, or None when it may (2026-11-14:
the orchestrator holds no code package and runs no coders; it holds only root files,
docs, manifests and scripts, and its guard refuses an edit inside a code package folder and names
the lane that should own it).

zone-guard.py asks it, for the orchestrator's session (ORC_ZONE), before each edit, each shell
write the guard checks (redirects, tee, sed -i, cp, mv, rm, touch, ...), each path git rm, mv,
restore, checkout and stash push name (orc_pathspec.py reads the pathspec) and the repository
top of git clean, reset --hard/--merge/--keep, stash pop/apply/branch, a stash push or save with
no pathspec (so a bare `git stash` in a tree holding a package is refused), and rm, mv,
restore (not --staged alone), checkout or stash push with --pathspec-from-file. Only the team's trees count:
the team root (the manifest's worktree_root) and the repo checkout (its `repo`). A folder is
refused when a code package folder lies inside it (`rm -rf crates`), and a path with glob
characters in any part is judged by what it matches (`rm -rf crates/*`, `crates/*/src/x.rs`), or
as written when it matches nothing (a new `crates/cli/src/*.zz` is inside crates/cli). A package
is judged against its tree top: the nearest .git or .jj at or above it, else by position
<team>/wo/<lane>/<name>; a marker folder that is its own tree top is no package. Inside the team
root a path with no tree top is still searched, and a package found there has no lane. The lanes
and their areas come from lane_walls, read as the orchestrator's walls (lane "orc", zone "."), so
the owner it names is the lane whose area covers the path; the orc itself is never named.
orchestrator_owns is not read, so an orchestrator_owns path inside a package is refused too and
named for the lane that covers it.

What is checked:
- IN: any write or removal that would change a file inside a code package folder, including
  removing a folder that contains a package. A pathspec file is not read: a git command that
  writes the worktree from --pathspec-from-file is judged by the whole repository top.
- OUT (accepted limits): the guard's existing fail-open forms (`cd $VAR`, xargs, find -exec and
  similar), interpreter writes (python -c, perl -e), git aliases, git merge (it brings
  reviewed content, and the orchestrator's merges need it), git add (staging writes no
  file), a branch switch (git switch; git checkout <branch>, whose name is judged as a path and
  passes unless it names a package folder), and exclude pathspecs (`:!`, `:^`,
  `:(exclude)`), which are not writes and are skipped. Also, by construction of the
  search: a WALK_SKIP folder is checked for a marker directly inside it but not walked into, so
  a package deeper inside one is not found from above (an edit inside it is still caught).
"""
import glob
import os
import tomllib
from pathlib import Path

import lane_walls
from code_package_folder import PACKAGE_MARKERS, code_package_folder

GLOB_CHARS = frozenset("*?[")
# Not walked into when searching for a package below a folder: version control and build
# output, which can be huge (the guard runs before every orc write).
WALK_SKIP = frozenset({".git", ".jj", "target", "cargo-target", ".build", "node_modules", "DerivedData"})
# A tree's top by position below the team root: a work order tree, wo/<lane>/<name> (3 parts).
TREE_DEPTH = {"wo": 3}


def _under(real: str, folder: Path) -> bool:
    top = os.path.realpath(folder)
    return real == top or real.startswith(top + os.sep)


def _tree_top(real: Path, team: Path) -> Path | None:
    """The nearest folder at or above real holding .git or .jj, else by position the
    wo/<lane>/<name> folder of the (real) team root that real lies in, else None."""
    repo = next((a for a in [real, *real.parents] if (a / ".git").exists() or (a / ".jj").exists()), None)
    if repo is not None or team not in real.parents:
        return repo
    parts = real.relative_to(team).parts
    n = TREE_DEPTH.get(parts[0], 0)
    return team.joinpath(*parts[:n]) if n and len(parts) >= n else None


def _package_below(folder: str, team: Path) -> tuple[Path, Path | None] | None:
    """The first code package folder inside folder and its tree top, walking in sorted order; a
    package's own subfolders are not searched, a tree top's are. A WALK_SKIP folder is not walked
    into, but counts when a marker lies directly inside it."""
    for dirpath, dirs, files in os.walk(folder):
        here = Path(dirpath)
        found = [here] if any(m in files for m in PACKAGE_MARKERS) else []
        found += [here / d for d in sorted(dirs)
                  if d in WALK_SKIP and any((here / d / m).is_file() for m in PACKAGE_MARKERS)]
        for pkg in found:
            top = _tree_top(pkg, team)
            if pkg != top:
                return pkg, top
        dirs[:] = sorted(d for d in dirs if d not in WALK_SKIP)
    return None


def _owner(walls: lane_walls.Walls, rels: tuple[str, str]) -> str | None:
    """The lane that owns the path or else its package; ORCHESTRATOR is what refused_by says for
    a path no lane holds, so it is no owner here, nor is the orc's own lane. Failing both, a
    whole-repo lane (path ".") covers it, never the orc itself (load_walls' fallback when
    team.json cannot be read)."""
    for rel in rels:
        who = lane_walls.refused_by(rel, walls)
        if who not in (None, lane_walls.ORCHESTRATOR, walls.lane):
            return who
    return next((n for n, r in walls.lanes.items() if n != walls.lane
                 and isinstance(r, dict) and str(r.get("path", "")).strip("/") == "."), None)


def _refusal(real: str, m: dict, codeteam_home: str | Path) -> str | None:
    """orc_package_refusal for one real path, the manifest already read as m."""
    team_root = Path(m.get("worktree_root") or f"~/codeteam-work/{m.get('product', '')}-team").expanduser()
    team = Path(os.path.realpath(team_root))
    in_team = _under(real, team_root)
    if not (in_team or (m.get("repo") and _under(real, Path(str(m["repo"])).expanduser()))):
        return None
    top = _tree_top(Path(real), team)
    if top is None and not in_team:
        return None
    pkg = code_package_folder(real, top or team)
    found = (pkg, top) if pkg else (_package_below(real, team) if os.path.isdir(real) else None)
    if found is None:
        return None
    pkg, top = found
    if top is None:
        return f"`{os.path.relpath(pkg, team)}` has no lane; its code would fall to the orchestrator"
    pkg_rel = os.path.relpath(pkg, top)
    rel = os.path.relpath(real, top) if _under(real, top) else pkg_rel
    walls = lane_walls.load_walls(lane="orc", zone=".", owns=(), team_json=team_root / "team" / "team.json",
                                  codeteam_home=codeteam_home)
    lane = _owner(walls, (rel, pkg_rel))
    if lane is None:
        return f"`{pkg_rel}` has no lane; its code would fall to the orchestrator"
    return (f"`{pkg_rel}` is a code package folder, lane {lane}'s: the orchestrator holds only "
            f"root files, docs, manifests and scripts; send the change to lane {lane}")


def orc_package_refusal(path: str | Path, manifest: str | Path, codeteam_home: str | Path) -> str | None:
    """The refusal for an orc write to path, naming the package and its lane, or None when the
    path is outside the team root and the repo checkout, or in no tree and outside the team root,
    or neither in nor holding a code package folder. A missing, unreadable or bad-TOML manifest gives None. A path
    with glob characters anywhere is judged by each match in sorted order, the first refusal
    returned, or as written when it matches nothing."""
    try:
        with open(manifest, "rb") as f:
            m = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    paths = (sorted(glob.glob(str(path))) or [path]) if GLOB_CHARS & set(str(path)) else [path]
    return next(filter(None, (_refusal(os.path.realpath(p), m, codeteam_home) for p in paths)), None)
