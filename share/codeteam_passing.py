"""PASSING: the test-record results a reader that asks "did it pass" counts as passing.

NO TESTS (a run that exited 0 but whose whole output says no test ran, or that every test it found was skipped) fails
nothing, so a lane whose zone has no tests yet is not failed by every gate; readers that report or prove a result
show it as itself, never as PASS.
"""

PASSING = ("PASS", "NO TESTS")
