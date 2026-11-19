"""The CodeGraph blast answer the interface check reads."""

import json
import subprocess
from collections.abc import Callable


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def interface_blast(cg: str, tree: str, base: str, timeout: int,
                    run: Callable | None = None) -> tuple[dict, str | None]:
    """(the parsed `blast` of tree against base, None), or ({}, the error) when it times out or does not answer JSON;
    the no-answer error ends with the last 200 characters of its stderr, else its stdout."""
    try:
        r = (run or _run)([cg, "blast", "-b", base, "-f", "json", "-p", tree], timeout)
        return json.loads(r.stdout), None
    except subprocess.TimeoutExpired:
        return {}, "codegraph blast timed out"
    except ValueError:
        return {}, "codegraph blast gave no answer (no index?): " + (r.stderr or r.stdout).strip()[-200:]
