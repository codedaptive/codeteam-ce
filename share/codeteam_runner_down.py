"""runner_down_note: the watchdog's note to a team's orchestrator about a runner launchd shows as not running.

Codeteam-jj's queue-run exited 1 at every start for hours (a work order folder
that was not a git tree), launchd's KeepAlive restarted it into the same exit ("spawn scheduled"), and the watchdog's
notice ("landing queue runner not running") went to the owner alone. The note says what launchd says (the job's state, and
the last exit code when that run failed), where the runner's log is, and the command that reinstalls the runners."""
import re
from pathlib import Path

TOP_STATE = re.compile(r"^\tstate = (.+)$", re.M)            # the job's own line; nested ones have two tabs
LAST_EXIT = re.compile(r"^\tlast exit code = (.+)$", re.M)
LOGS = {"landing": "queue-run.log", "recheck": "recheck-run.log", "validation": "validate-run.log"}


def runner_down_note(problem: str, printed: str, root: Path, manifest: Path) -> str:
    """The note for `problem` ("landing queue runner not running"), given `printed` (the job's `launchctl print`
    output), the team's folder `root` and its manifest."""
    state, code = TOP_STATE.search(printed), LAST_EXIT.search(printed)
    said = [state.group(1).strip()] if state else []
    exit_code = code.group(1).strip() if code else ""
    if exit_code and exit_code not in ("0", "(never exited)"):
        said.append(f"last exit code {exit_code}, so it exits at start and launchd starts it again")
    launchd = f" (launchd: {', '.join(said)})" if said else ""
    log = Path(root) / "land" / LOGS.get(problem.split(" ")[0], "queue-run.log")
    return (f"watchdog: {problem}{launchd}. Its log is {log}. Once the cause is gone, "
            f"`codeteam-land {manifest} service install` starts the runners again.")
