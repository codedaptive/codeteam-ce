"""build_seconds: how long a landing step's zone-tool jobs spent building, from zone-tool's output.

the slow-test rule counts only the tests' run ("zone-tool times the build apart, and
the slow-test rule counts only the tests' run"). zone-tool prints each queue job's build time inside its run line, just before that
job's summary (print_done): `zone-tool: queued Q s, ran R s (job T, build B s)`. The sum of those B is the step's
build, which the landing takes out of the step's run.
"""
import re

# zone-tool's line before a queue job's summary when it timed the build, anchored like codeteam_ran's JOB_RAN.
JOB_BUILD = re.compile(r"^zone-tool: queued \d+ s, ran \d+ s \(job [^,)\n]+, build (\d+) s\)\nzone-test: ", re.M)


def build_seconds(text: str) -> int | None:
    """The build seconds of a step's zone-tool jobs, summed; None when no job line carries a build part, so the
    step's run counts whole."""
    builds = JOB_BUILD.findall(text)
    return sum(int(build) for build in builds) if builds else None
