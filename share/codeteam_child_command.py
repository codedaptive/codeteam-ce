"""child_command: the pytest command and environment zone-tool test-one gives the tests it runs (D526; moved
unchanged from cmd_test_one).

Children drop CODETEAM_* and HERDR_* except the keep list: an inherited CODETEAM_MANIFEST can make a hook test act
on a live team. Kept: codeteam's location, the build queue's variables, landing, D281's test group and the RIT
selector a calling zone's RIT step exports (D525); CODETEAM_TEST_GROUP and CODETEAM_RIT_SELECTOR name tests, not a
team. MAKEFLAGS, MFLAGS, MAKELEVEL, MAKEOVERRIDES and DIR go too, so a command-line DIR=x does not reach a test that
itself runs make.
"""
from collections.abc import Mapping

from codeteam_kinds_pytest_run import with_kinds

KEEP = ("CODETEAM_HOME", "CODETEAM_BUILD_JOBS", "CODETEAM_BUILDQ_TICKET", "CODETEAM_LANDING",
        "CODETEAM_TEST_GROUP", "CODETEAM_RIT_SELECTOR")
DROP = ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "DIR")


def child_command(environ: Mapping[str, str], py: str, group: str, kinds: bool) -> tuple[list[str], dict[str, str]]:
    """The pytest command (`-p no:cacheprovider`: no .pytest_cache folder in the worktree) and the children's
    environment; with `kinds` (CODETEAM_KINDS_BY_NAME=1), after saying so, both as with_kinds makes them for
    `group`."""
    env = {k: v for k, v in environ.items()
           if k not in DROP and (k in KEEP or not k.startswith(("CODETEAM_", "HERDR_")))}
    pytest = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if kinds:
        print(f"test-one: kinds by name (CODETEAM_KINDS_BY_NAME=1): this {group} run runs only tests named {group}; "
              "an unnamed test is a ZUT, unit run only")
        return with_kinds(pytest, env, group)
    return pytest, env
