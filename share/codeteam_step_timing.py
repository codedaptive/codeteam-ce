"""step_timing: a landing step's run and build seconds, from zone-tool's output, as result keys (R-26, D585).

R-26 limits a landing's tests by their run time; D585 times the build apart so the landing can take it out of the
run. codeteam_ran reads the run and codeteam_build_seconds the build; a step's result carries each only when the
output gives it, so a step whose output shows neither has no timing keys at all.
"""
import codeteam_build_seconds
import codeteam_ran


def step_timing(text: str) -> dict[str, int]:
    """"ran" (codeteam_ran.ran_seconds) and "build" (codeteam_build_seconds.build_seconds) of a step's output, each
    only when its reader finds it (0 is kept: a step answered from its record ran 0 seconds)."""
    timing = {"ran": codeteam_ran.ran_seconds(text), "build": codeteam_build_seconds.build_seconds(text)}
    return {key: seconds for key, seconds in timing.items() if seconds is not None}
