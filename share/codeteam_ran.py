"""ran_seconds: how long a landing step's tests ran, from zone-tool's output, waits excluded.

the slow-test rule limits a landing's tests by their run time, not their waiting time. A step's wall-clock seconds include every
wait before its zone-tool jobs ran: the build queue, and any lock a team's test command takes before it submits a
job (Widgets's lockf serializes the steps started together, slow#2). zone-tool prints each queue job's own run time
on the line just before that job's summary (print_done), so the sum of those is the step's run, which includes any
build the jobs did (the landing takes that out, codeteam_build_seconds). A step that zone-tool answered from
its record ran nothing.
"""
import re

# zone-tool's line before a queue job's summary (print_done), anchored like codeteam-land's QUEUED.
JOB_RAN = re.compile(r"^zone-tool: queued \d+ s, ran (\d+) s \(job [^)\n]+\)\nzone-test: ", re.M)

# zone-tool's answers from a record, which run no tests: the exact code's record, a record whose inputs have not
# changed (both from zone-test), and a queue job answered from its record (print_done).
RAN_NOTHING = re.compile(r"^zone-test: \S+ at \d\d:\d\d already recorded(?: for this exact code|; nothing these tests "
                         r"touch has changed since); not run again$"
                         r"|^zone-test: \S+ \(exit [^)\n]+\); answered from record \S", re.M)


def ran_seconds(text: str) -> int | None:
    """The run seconds of a step's zone-tool jobs, build included, summed; 0 when zone-tool answered from a record and
    ran no job; None when the output shows neither."""
    runs = JOB_RAN.findall(text)
    if runs:
        return sum(int(run) for run in runs)
    return 0 if RAN_NOTHING.search(text) else None
