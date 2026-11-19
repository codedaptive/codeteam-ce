"""The failing tests a test log names, whatever ran them.

Each runner names a failure its own way: Rust's libtest, XCTest, xcodebuild's per-case line, pytest's summary,
vitest's summary, xcodebuild's indented 'Failing tests:' list and Swift Testing's 'Test x failed after' line.
"""

import re

from codeteam_vitest_failures import vitest_failures

FAILING_TEST_LINES = (
    re.compile(r"^test (\S+) \.\.\. FAILED$"),                              # Rust (cargo test, nextest's libtest)
    re.compile(r"Test Case '-\[(\S+) (\S+)\]' failed \("),                  # XCTest
    re.compile(r"Test case '([^']+)' failed"),                              # xcodebuild's per-case line
    re.compile(r"FAILED (\S+::\S+)"),                                       # pytest's summary
)
SWIFT_TESTING_FAILED = re.compile(r"(?:^|\s)Test (.+?) failed after [\d.]+ seconds")


def _line_name(stripped: str) -> str | None:
    for pattern in FAILING_TEST_LINES:
        if m := pattern.search(stripped):
            return ".".join(m.groups())
    return None


def _swift_testing_name(stripped: str) -> str | None:
    m = SWIFT_TESTING_FAILED.search(stripped)
    return m[1] if m and not m[1].startswith("run with ") else None


def _scan(text: str) -> tuple[list[str], list[str], list[str]]:
    """The names from the per-line patterns, from the 'Failing tests:' list, and from Swift Testing's lines."""
    names, listed, swift = [], [], []
    in_list = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_list and stripped and line[:1].isspace():
            listed.append(stripped)
            continue
        in_list = stripped == "Failing tests:"
        if in_list:
            continue
        if (name := _line_name(stripped)) is not None:
            names.append(name)
        elif (name := _swift_testing_name(stripped)) is not None:
            swift.append(name)
    return names, listed, swift


def failing_test_names(text: str) -> list[str]:
    """The failing tests a test log names, in order, once each: Rust, XCTest, pytest, vitest ('<file> > ... > <test>';
    a failing file names no test), and Swift tests from xcodebuild's 'Failing tests:' list or, when a log has none,
    Swift Testing's 'Test x failed after' lines (whose glyph prefix differs between swift test and xcodebuild)."""
    names, listed, swift = _scan(text)
    vitest = [name for _, name in vitest_failures(text) if name is not None]
    return list(dict.fromkeys(names + vitest + (listed or swift)))
