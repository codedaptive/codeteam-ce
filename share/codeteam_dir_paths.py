"""dir_paths: the paths zone-tool test-one's DIR names (D526; moved unchanged from cmd_test_one).

A DIR that resolves to the repo root (., ./, zone/.., the root's absolute path) means the lane's owned paths: each
colon-separated entry of CODETEAM_OWNS, glob-expanded from the root. Any other DIR is itself.
"""
import glob
from collections.abc import Mapping
from pathlib import Path


def dir_paths(target: str, root: Path, environ: Mapping[str, str]) -> list[tuple[str, bool]] | None:
    """(path relative to root, owned) for each path to plan; None, after saying why, for the root with
    CODETEAM_OWNS empty or unset (refused rather than passing with no tests or running the whole repo)."""
    # Resolved, not compared as text: ./ or zone/.. is the root too, and must not run as a
    # plain folder (pytest over every lane's tests).
    if (root / target).resolve() != root.resolve():
        return [(target, False)]
    owns = [e for e in environ.get("CODETEAM_OWNS", "").split(":") if e]
    if not owns:
        print(f"test-one: DIR={target} is the repo root, which means the lane's owned "
              "paths, and CODETEAM_OWNS is empty; set CODETEAM_OWNS or give DIR a folder")
        return None
    return [(m, True) for e in owns for m in sorted(glob.glob(e, root_dir=root))]
