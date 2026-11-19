"""The landing, recheck and validation runners a promote of one checkout of codeteam's tools changes.

A runner runs whatever bin/codeteam-land its launchd job names, and its manifest can live in another repo: production's
runners serve a v5.5 checkout's manifest, and a v5.5 checkout's fork runs sprocket's and linter's. So the runners to
restart after a promote of a checkout are found from the installed jobs' programs, not from the checkout's teams/
(sprocket's runners kept two-day-old code through about 30 of the fork's promotes).
"""
from pathlib import Path
import plistlib

LABELS = ("com.codeteam.codeteam-land", "com.codeteam.codeteam-recheck", "com.codeteam.codeteam-validate")


def runner_jobs(repo: Path, agents: Path) -> list[tuple[Path, str]]:
    """(manifest, subcommand) of each runner job in agents whose program is repo's bin/codeteam-land, in job file
    name order. A job is the four ProgramArguments codeteam-land installs: Python, the program, the manifest, the
    subcommand. A job file that cannot be read is skipped, since launchd cannot run it either."""
    program = (Path(repo) / "bin" / "codeteam-land").resolve()
    jobs = []
    for plist in sorted(path for label in LABELS for path in Path(agents).glob(f"{label}.*.plist")):
        try:
            args = plistlib.loads(plist.read_bytes()).get("ProgramArguments", [])
        except (OSError, ValueError):
            continue
        if len(args) == 4 and Path(args[1]).resolve() == program:
            jobs.append((Path(args[2]), args[3]))
    return jobs
