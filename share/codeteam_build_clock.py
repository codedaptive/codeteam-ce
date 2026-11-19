"""BuildClock: how many seconds of a test run's output were spent building, read from the output itself.

A build is not test run time (the slow-test rule): zone-tool records the
build seconds beside the run's seconds, so a slow compile is not read as slow tests. The clock is pure: the caller
passes each line with its time and the run's end time, and it keeps a few numbers, never the lines, since a run
can print millions of them.

What counts as building:
- cargo's `Finished ... target(s) in [Nh ][Nm ]X[.Y]s` and SwiftPM's `Build complete! (X.Ys)` report their own
  duration; a `Finished` line without `target(s) in` (another tool's) adds nothing;
- an xcodebuild build phase opens at a `Command line invocation:` line whose next non-blank line has `build`,
  `build-for-testing` or `test` among its words, and closes at the first later build verdict or `Testing started`
  line; a phase still open when the run ends runs to its end.

record(end) is the record's part, {"build_seconds": seconds rounded to 0.1}.
"""
import re

_CARGO = re.compile(r"\bFinished\b.* target\(s\) in (?:(\d+)h )?(?:(\d+)m )?(\d+(?:\.\d+)?)s$")
_SWIFTPM = re.compile(r"\bBuild complete! \((\d+(?:\.\d+)?)s\)")
_INVOCATION = "Command line invocation:"
# `test-without-building` is absent on purpose: it builds nothing.
_BUILD_ACTIONS = frozenset({"build", "build-for-testing", "test"})
_CLOSERS = frozenset({"** TEST BUILD SUCCEEDED **", "** TEST BUILD FAILED **",
                      "** BUILD SUCCEEDED **", "** BUILD FAILED **"})


class BuildClock:
    """Feed every output line with line(t, text); seconds(end) is the build time so far."""

    def __init__(self) -> None:
        self._total = 0.0
        self._invoked_at: float | None = None  # an invocation line waiting for its command line
        self._phase_start: float | None = None  # an open xcodebuild build phase

    def line(self, t: float, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        if stripped == _INVOCATION:
            self._invoked_at = t
            return
        if self._invoked_at is not None:
            if self._phase_start is None and _BUILD_ACTIONS.intersection(stripped.split()):
                self._phase_start = self._invoked_at
            self._invoked_at = None
            return
        if self._phase_start is not None and (stripped in _CLOSERS or stripped.startswith("Testing started")):
            self._total += t - self._phase_start
            self._phase_start = None
            return
        self._total += _reported(stripped)

    def seconds(self, end: float) -> float:
        return float(self._total + (end - self._phase_start if self._phase_start is not None else 0.0))

    def record(self, end: float) -> dict:
        return {"build_seconds": round(self.seconds(end), 1)}


def _reported(stripped: str) -> float:
    """The duration cargo or SwiftPM printed on this line, or 0."""
    if m := _CARGO.search(stripped):
        hours, minutes, secs = m.groups()
        return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(secs)
    if m := _SWIFTPM.search(stripped):
        return float(m.group(1))
    return 0.0
