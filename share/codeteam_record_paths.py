"""record_paths: the test-record files a landing step's zone-test runs wrote, from its output (codeteam-jj #4664
item 3, D554).

zone-test ends each run with one summary line naming its record, `zone-test: <VERDICT> (exit N); record <path>`.
Stage 2 keeps those files at landing (codeteam_keep_stage2_records), since the step's tree is removed then and the
next run in a shared tree writes over them.
"""
import re

SUMMARY = re.compile(r"^zone-test: (?:PASS|FAIL|HUNG|BROKEN|NO TESTS) \(exit [^)\n]*\); record (\S+)\s*$", re.M)


def record_paths(text: str) -> list[str]:
    """The record paths on text's zone-test summary lines, in order, each once."""
    return list(dict.fromkeys(SUMMARY.findall(text)))
