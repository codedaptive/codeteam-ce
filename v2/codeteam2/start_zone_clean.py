"""Start a detached `make zone-clean` in one tree (D598).

The loop calls this once a lane it ended for idleness is seen gone, so the clean must never hold the loop: make
runs in its own session behind a `/bin/sh -c '... &'` that exits at once. The loop waits for that sh straight
away, so no zombie is left, and never waits for make. The environment is the one the landing runner's idle clean
gives zone-clean (bin/codeteam-land, clean_idle), plus ZONE_CLEAN_KEEP_INDEX=1 so the tree's CodeGraph index
survives the clean. Best effort: a missing tree or a failed launch of that sh is False, never an exception. The
sh looks make up in the background after this has returned, so True says only that the sh was started: a missing
make still gives True.
"""
import os
import shlex
import subprocess
from pathlib import Path


def start_zone_clean(tree: Path, ct_home: Path) -> bool:
    """True when the detached sh that runs zone-clean was started in tree; False when tree is no directory or the
    sh fails to start."""
    if not Path(tree).is_dir():
        return False
    env = dict(os.environ, MAKEFILES=str(Path(ct_home) / "zone" / "zone.mk"), CODETEAM_HOME=str(ct_home),
               ZONE_CLEAN_KEEP_INDEX="1")
    cmd = shlex.join(["make", "--no-print-directory", "zone-clean"])
    try:
        subprocess.Popen(["/bin/sh", "-c", f"{cmd} </dev/null >/dev/null 2>&1 &"], cwd=tree, env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True).wait()
    except OSError:
        return False
    return True
