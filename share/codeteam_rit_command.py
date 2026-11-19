"""The command that runs only a root's repo integration tests.

A team that names its RITs ([land] rit_selector) runs, for a zone that only calls the changed zone, the RITs in that
zone's reached roots instead of its whole integration test group. The team may give the command ([land] rit_test); otherwise a
zone-test-one template gets the selector as both ports' test-name filter (widgets's test_one.sh takes a bare
CARGO_TEST_ARGS name as the filter). CODETEAM_RIT_SELECTOR names the selector to whatever the command runs: it is
exported, so every part of a compound rit_test sees it, and zone-tool test-one passes it to the tests it runs.
"""
import shlex


def rit_command(template: str, selector: str, rit_template: str | None = None) -> str | None:
    """The RIT-only command, with {dir}, {zone} and {cls} left for the caller; None when `template` is not a
    zone-test-one and no `rit_template` is given (the caller runs the root's whole integration test step)."""
    quoted = shlex.quote(selector)
    if rit_template is not None:
        command = rit_template.replace("{selector}", quoted)
    elif "zone-test-one" in template:
        command = f"{template} CARGO_TEST_ARGS={quoted} SWIFT_TEST_ARGS={shlex.quote('--filter ' + selector)}"
    else:
        return None
    return f"export CODETEAM_RIT_SELECTOR={quoted}; {command}"
