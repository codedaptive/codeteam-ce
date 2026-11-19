"""A calling zone's RIT steps in mode (a) (D491, creator #4379 Q-stage2-reach2).

With [land] rit_selector set, a reached zone that holds no changed file runs its RITs, not its whole ZIT group: its
lane's own test with the selector exported, which picks them, or the RITs in its reached roots. codeteam-land passes its
own step builders in, so the steps are named, keyed and queued as its zone_tests builds them.
"""
import shlex
from collections.abc import Callable

from codeteam_rit_command import rit_command


def rit_steps(team, tree, zone: str, selector: str, files: list[str], *, zone_tests: Callable, test_folders: Callable,
              rit_roots: Callable, lane_rec: Callable, lane_test_key: Callable, zone_tool: str,
              test_template: str) -> list[tuple[str, str]]:
    """The zone's RIT steps: its lane's own `test` command with CODETEAM_RIT_SELECTOR exported, so every part of a
    compound test sees it (`A && B`; an `X=v` prefix reaches only A), through the queue under the key
    `<lane test key> rits`; else one step `rits <zone> (<dir>)` per reached root that holds the selector
    (rit_roots), running rit_command's command. A team test command rit_command cannot narrow runs the zone's
    integration group instead."""
    lane = lane_rec(team, zone)
    if lane.get("test"):
        key = lane_test_key(zone, "integration") + " rits"
        command = f"export CODETEAM_RIT_SELECTOR={shlex.quote(selector)}; {lane['test']}"
        return [(f"rits {zone} (its lane's test)", f"{zone_tool} job submit --class land --wait 0 --key "
                                                   f"{shlex.quote(key)} -- sh -c {shlex.quote(command)}")]
    template = rit_command(team.c("test", test_template), selector, team.c("rit_test", None))
    if template is None:
        return zone_tests(team, tree, zone, "land", group="integration", files=files)
    return [(f"rits {zone} ({d})", template.replace("{dir}", shlex.quote(d)).replace("{zone}", shlex.quote(zone))
             .replace("{cls}", "land"))
            for d in rit_roots(tree, test_folders(team, tree, zone, "integration", files), selector)]
