"""The integration steps for the zones a landing reaches, at Stage 2 and in the recheck.

Stage 5's recheck follows the same rule as Stage 2, so both build their integration steps here from the
same arguments. Without [land] rit_selector (mode b) every reached zone runs its integration group over the roots
the change reaches. With it (mode a) a zone that owns a changed non-doc file runs that group and every other reached
zone runs only its RITs. With no changed files (an older recheck row) nothing tells the changed zones apart, so every
reached zone runs its integration group, as in (b). codeteam-land passes its own step builders in.
"""
from collections.abc import Callable, Iterable

from codeteam_owning_zone import owning_zone
from codeteam_reached_zone_steps import reached_zone_steps
from codeteam_rit_steps import rit_steps


def zone_steps(team, tree, zones: Iterable[str], files: Iterable[str], *, in_scope: Callable, zone_tests: Callable,
               test_folders: Callable, rit_roots: Callable, lane_rec: Callable, lane_test_key: Callable,
               repo_integration_steps: Callable, zone_tool: str, test_template: str) -> list[tuple[str, str]]:
    """The reached zones' steps (mode a or (b) above), then the repo integration folder's scripts that reach a
    changed file; with no files, all of them. Each distinct command runs once, under the first step's name: two
    reached zones can own one folder (LedgerKit owns packages/libs/CipherLib, which the
    packages/libs/* glob makes a zone too), and the same command on the same tree is the same run, as
    zone_check_steps already does for the compile check."""
    files = list(files)
    selector = team.c("rit_selector", None) if files else None
    docs = tuple(team.c("docs_only_suffixes", [".md"]))
    changed = {owning_zone(team.zones, f, in_scope) for f in files if not f.endswith(docs)} if selector else set()
    steps = reached_zone_steps(
        list(zones), changed, selector,
        lambda z: zone_tests(team, tree, z, "land", group="integration", files=files),
        lambda z: rit_steps(team, tree, z, selector, files, zone_tests=zone_tests, test_folders=test_folders,
                            rit_roots=rit_roots, lane_rec=lane_rec, lane_test_key=lane_test_key,
                            zone_tool=zone_tool, test_template=test_template))
    folder = team.c("integration_tests", "tests/integration")
    steps += (repo_integration_steps(tree, folder, "land", zone_tool, files=files, docs=docs) if files
              else repo_integration_steps(tree, folder, "land", zone_tool))
    once = {}
    for name, command in steps:
        once.setdefault(command, (name, command))
    return list(once.values())
