"""Shared helpers for v2's tests: the integration-group marker."""
import os
import unittest

# Cases that depend on real processes, timed waits, network, herdr or the build queue belong in integration.
# This marker skips them unless CODETEAM_TEST_GROUP=integration; zone-tool test-one passes that variable through
# to its test children. unittest.skipUnless, not a pytest mark, also works when unittest runs the cases.
integration_only = unittest.skipUnless(
    os.environ.get("CODETEAM_TEST_GROUP", "unit") == "integration",
    "integration group only; run with CODETEAM_TEST_GROUP=integration",
)
