"""The record of every watchdog action.

One parseable `watchdog {json}` line in the loop's log and the same object appended to <team dir>/watchdog.jsonl,
so it can be read later whether an action was needed: for example whether an answer to the request it gave up on
arrived afterwards.
"""
import json
from pathlib import Path


def watch_record(team_dir, log, fields: dict) -> None:
    line = json.dumps(fields, sort_keys=True)
    log("watchdog " + line)
    with open(Path(team_dir) / "watchdog.jsonl", "a") as f:
        f.write(line + "\n")
