"""The lines of a validation log that name its failures, chosen the way the remote run's `grep -hE | tail -400` does.

FAILURE_LINES is handed to grep -E on the validation machine as well as used here, so it keeps to what both grep -E
and Python's re read alike: no \\s, \\d or \\x escapes. It selects codeteam's FAILED ZONES / FAILED MODULES lines,
libtest's `test x ... FAILED` lines and vitest's summary lines. A vitest summary line starts ` FAIL ` in a plain log;
in a coloured one the word sits after a colour code ending in `m` (`ESC[1m FAIL ESC[22m`). The parsers that read the
selected lines are strict and name nothing from a stray line such as `Platform FAIL here`, but it still takes one of
the 400 kept lines.
"""

import re

FAILURE_LINES = r"FAILED (ZONES|MODULES):|^test .* FAILED$|^ +FAIL |m FAIL "

# The remote run keeps this many matching lines (its `tail -400`).
_KEEP = 400


def failure_lines(text: str) -> str:
    """The lines of text that match FAILURE_LINES, the last 400, each ending in a newline: the same selection the
    remote run's grep makes; "" when none match."""
    lines = [line for line in text.split("\n") if re.search(FAILURE_LINES, line)]
    return "".join(line + "\n" for line in lines[-_KEEP:])
