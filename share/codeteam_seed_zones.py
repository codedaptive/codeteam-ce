"""The zones other than the work order's own that call one changed declaration, from CodeGraph's callers."""

import json
import subprocess
from collections.abc import Callable

from codeteam_codegraph_complete import CODEGRAPH_LIMIT, codegraph_complete
from codeteam_json_paths import json_paths

_TIMEOUT_S = 60     # one query on a built index answers in seconds; a hung server must not hold the landing


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S).stdout


def seed_zones(cg: str, tree: str, seed: dict, zone_of: Callable[[str], str | None], own_zone: str,
               run: Callable[[list[str]], str] | None = None) -> tuple[dict[str, list[str]], dict]:
    """({zone: its files calling seed, sorted and each once}, with own_zone and files in no zone left out; {} or the
    interface_error to record). An incomplete answer keeps the zones and files it names and says calling zones may be
    missing; a query that times out or answers no JSON gives {} and names the exception."""
    name = seed["name"]
    try:
        answer = json.loads((run or _run)([cg, "callers", name, "-f", seed["path"], "-p", tree, "-j",
                                           "-l", str(CODEGRAPH_LIMIT)]))
    except (subprocess.TimeoutExpired, ValueError) as ex:
        return {}, {"interface_error": f"codegraph callers {name}: {type(ex).__name__}"}
    zones: dict[str, list[str]] = {}
    for path in sorted(set(json_paths(answer))):
        zone = zone_of(path)
        if zone and zone != own_zone:
            zones.setdefault(zone, []).append(path)
    if codegraph_complete(answer, "callers"):
        return zones, {}
    return zones, {"interface_error": f"codegraph callers {name}: incomplete answer, calling zones may be missing"}
