"""Shared helpers for v2's tests: the integration-group marker (D281, D285, D300)."""
import os
import unittest

import pytest

# Cases that depend on real processes, timed waits, network, herdr or the build queue belong in integration (D281).
# This marker skips them unless CODETEAM_TEST_GROUP=integration; zone-tool test-one passes that variable through
# to its test children (D299). unittest.skipUnless, not a pytest mark, also works when unittest runs the cases.
INTEGRATION = os.environ.get("CODETEAM_TEST_GROUP", "unit") == "integration"
WHY = "integration group only (D281); run with CODETEAM_TEST_GROUP=integration"
integration_only = unittest.skipUnless(INTEGRATION, WHY)

# The same group for a pytest module whose fixtures cross the line (real git, /bin/sh): `pytestmark =
# integration_module`. It skips before the fixtures run; integration_only on a plain function skips only after
# pytest has run them (D464).
integration_module = pytest.mark.skipif(not INTEGRATION, reason=WHY)
