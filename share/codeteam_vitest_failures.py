"""The failing vitest tests and files a test log names.

vitest's summary prints one line per failure: `FAIL`, an optional project label, the test file, then either
` > describe > ... > test` (a failing test), ` [ file ]` (a file that failed to load or run) or nothing. Colour codes
are stripped first, since a log written from a terminal keeps them between every token.
"""

import re

_CSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_SUMMARY = re.compile(r"^\s*FAIL\s+(?:\S+\s+)?(\S+\.[A-Za-z0-9]+)(?:( > .+)| \[ .* \])?$")


def vitest_failures(text: str) -> list[tuple[str, str | None]]:
    """(file, "<file> > ... > <test>") for each failing test and (file, None) for each failing file, in order of first
    appearance, once each."""
    pairs = []
    for line in text.split("\n"):
        if m := _SUMMARY.match(_CSI.sub("", line)):
            pairs.append((m[1], m[1] + m[2] if m[2] else None))
    return list(dict.fromkeys(pairs))
