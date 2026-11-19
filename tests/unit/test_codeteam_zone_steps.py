"""share/codeteam_zone_steps.py alone: the reached zones' integration steps run each distinct command once.
The step builders are fakes; reached_zone_steps is used as it is (a one-line choice between them)."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "share"))
spec = importlib.util.spec_from_file_location("codeteam_zone_steps", ROOT / "share" / "codeteam_zone_steps.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode

# LedgerKit owns packages/libs/CipherLib, and the packages/libs/* glob makes that
# folder the CipherLib zone too, so both zones' steps name the same command.
FOLDERS = {"LedgerKit": ["packages/kits/LedgerKit", "packages/libs/CipherLib"],
           "CipherLib": ["packages/libs/CipherLib"], "SafeKit": ["packages/kits/SafeKit"]}


def zone_tests(team, tree, zone, cls, group, files):
    return [(f"tests {zone} ({folder})", f"make zone-test-one DIR={folder} CLASS={cls}") for folder in FOLDERS[zone]]


def steps(zones, repo_steps=()):
    team = SimpleNamespace(c=lambda key, default: default, zones=FOLDERS)
    unused = lambda *args, **kwargs: []
    return module.zone_steps(team, "/tree", zones, ["packages/libs/CipherLib/x.c"], in_scope=unused,
                             zone_tests=zone_tests, test_folders=unused, rit_roots=unused, lane_rec=unused,
                             lane_test_key=unused, repo_integration_steps=lambda *args, **kwargs: list(repo_steps),
                             zone_tool="zone-tool", test_template="")


def test_a_folder_two_reached_zones_own_runs_once_under_the_first_zone_s_name():
    assert steps(["LedgerKit", "CipherLib", "SafeKit"]) == [
        ("tests LedgerKit (packages/kits/LedgerKit)", "make zone-test-one DIR=packages/kits/LedgerKit CLASS=land"),
        ("tests LedgerKit (packages/libs/CipherLib)", "make zone-test-one DIR=packages/libs/CipherLib CLASS=land"),
        ("tests SafeKit (packages/kits/SafeKit)", "make zone-test-one DIR=packages/kits/SafeKit CLASS=land")]


def test_the_shared_folder_keeps_the_zone_that_reaches_it_first():
    assert steps(["CipherLib", "LedgerKit"]) == [
        ("tests CipherLib (packages/libs/CipherLib)", "make zone-test-one DIR=packages/libs/CipherLib CLASS=land"),
        ("tests LedgerKit (packages/kits/LedgerKit)", "make zone-test-one DIR=packages/kits/LedgerKit CLASS=land")]


def test_repo_integration_steps_follow_and_a_repeated_one_runs_once():
    repo = [("integration tests (tests/integration)", "python3 -m pytest -q tests/integration")] * 2
    assert steps(["SafeKit"], repo) == [
        ("tests SafeKit (packages/kits/SafeKit)", "make zone-test-one DIR=packages/kits/SafeKit CLASS=land"),
        ("integration tests (tests/integration)", "python3 -m pytest -q tests/integration")]
