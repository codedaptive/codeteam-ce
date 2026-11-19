"""codeteam_kinds_pytest: a pytest plugin that runs one test kind by name (the test kinds rule).

Load it with `-p codeteam_kinds_pytest` (share/ on PYTHONPATH) and name the kind with --codeteam-kind. Without the
option it does nothing. A test under a unit, integration or validation folder is that kind. An unnamed test is a
unit test and runs only in the unit run, unless it is one that a unit run would not run: a test its own markers skip
under CODETEAM_TEST_GROUP=unit (a skipif or unittest.skipUnless gate), or one a unit run does not collect. Those
decide their own group, so the integration and validation runs keep them and their markers skip the rest.

Which unnamed tests a unit run would run is asked of pytest itself: a probe re-runs this collection with
--collect-only under CODETEAM_TEST_GROUP=unit and GROUP=unit, and this plugin, in probe mode, writes the nodeids it
collected and did not skip. A probe that writes nothing fails the run loudly; selecting without it would guess.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from codeteam_folder_kind import KINDS, folder_kind

KIND_OPTION = "--codeteam-kind"
PROBE_OPTION = "--codeteam-kind-probe"
PLUGIN = "codeteam_kinds_pytest"
PROBE_OUTPUT_LINES = 20


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("codeteam kinds")
    group.addoption(KIND_OPTION, choices=KINDS, default=None,
                    help="run only this test kind; unnamed tests are unit tests, run only in the unit run")
    group.addoption(PROBE_OPTION, default=None, help="internal: write the nodeids a unit run would run to this file")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    probe_file = config.getoption(PROBE_OPTION)
    if probe_file:
        _write_unit_nodeids(Path(probe_file), items)
        return
    kind = config.getoption(KIND_OPTION)
    if kind:
        _select(config, items, kind)


def _write_unit_nodeids(probe_file: Path, items: list[pytest.Item]) -> None:
    try:
        from _pytest.skipping import evaluate_skip_marks
    except ImportError as error:
        raise pytest.UsageError(f"codeteam kinds: cannot read skip marks ({error}); no kind can be selected")
    running = [item.nodeid for item in items if not _skipped(item, evaluate_skip_marks)]
    probe_file.write_text(json.dumps(running))


def _skipped(item: pytest.Item, evaluate_skip_marks) -> bool:
    return (evaluate_skip_marks(item) is not None
            or getattr(getattr(item, "obj", None), "__unittest_skip__", False)
            or getattr(getattr(item, "cls", None), "__unittest_skip__", False))


def _select(config: pytest.Config, items: list[pytest.Item], kind: str) -> None:
    kinds = [(item, folder_kind(Path(os.path.relpath(item.path, config.invocation_params.dir)).as_posix())) for item in items]
    if kind == "unit":
        keep = [item_kind in (None, "unit") for _, item_kind in kinds]
    else:
        unit_run = _probe_unit_run(config) if any(item_kind is None for _, item_kind in kinds) else set()
        keep = [item_kind == kind or (item_kind is None and item.nodeid not in unit_run) for item, item_kind in kinds]
    kept = [item for item, keeps in zip(items, keep) if keeps]
    dropped = [item for item, keeps in zip(items, keep) if not keeps]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
    config.get_terminal_writer().line(
        f"codeteam kinds: group {kind}: {len(kept)} selected, {len(dropped)} deselected "
        "(unnamed tests are unit tests, unit run only)")


def _probe_unit_run(config: pytest.Config) -> set[str]:
    env = dict(os.environ, CODETEAM_TEST_GROUP="unit", GROUP="unit")
    with tempfile.TemporaryDirectory(prefix="codeteam-kinds-") as folder:
        probe_file = Path(folder) / "unit-nodeids.json"
        command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-p", PLUGIN,
                   f"{PROBE_OPTION}={probe_file}", *_probe_args(config.invocation_params.args)]
        result = subprocess.run(command, cwd=config.invocation_params.dir, env=env, capture_output=True, text=True)
        if not probe_file.exists():
            tail = "\n".join((result.stdout + result.stderr).splitlines()[-PROBE_OUTPUT_LINES:])
            raise pytest.UsageError(f"codeteam kinds: the unit probe wrote no nodeids (exit {result.returncode}); "
                                    f"no kind can be selected. Its last output:\n{tail}")
        return set(json.loads(probe_file.read_text()))


def _probe_args(args: tuple[str, ...]) -> list[str]:
    """The run's own arguments without this plugin's options and without the -p pairs the probe adds itself."""
    kept: list[str] = []
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg.startswith((f"{KIND_OPTION}=", f"{PROBE_OPTION}=")):
            continue
        if arg in (KIND_OPTION, PROBE_OPTION) or (
                arg == "-p" and index + 1 < len(args) and args[index + 1] in ("no:cacheprovider", PLUGIN)):
            skip_next = True
            continue
        kept.append(arg)
    return kept
