import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_recheck_owner import recheck_owner

ROWS = [{"wo": "one", "M": "m1", "zones": ["A", "B"], "overlapping": []},
        {"wo": "two", "M": "m2", "zones": ["B"], "overlapping": ["p"]},
        {"wo": "three", "M": "m3", "zones": ["C"], "overlapping": []}]
BATCH = {"wo": "three", "M": "m3", "batch": ["one", "two", "three"]}
ZONES = {"tests B (b)": "B", "tests A (a)": "A", "tests Z (z)": "Z"}


def owner():
    return recheck_owner(ROWS, BATCH, ZONES.get, lambda wo: {"wo": wo, "zone": "landed-" + wo},
                         lambda name: "never")


def test_newest_row_reaching_the_zone_owns_it_at_the_batch_commit():
    assert owner()({"name": "tests B (b)"}) == (
        {"wo": "two", "M": "m3", "zones": ["B"], "overlapping": ["p"]}, {"wo": "two", "zone": "landed-two"})
    assert owner()({"name": "tests A (a)"})[0]["wo"] == "one"
    assert ROWS[1]["M"] == "m2"


def test_unreached_or_unknown_zone_goes_to_the_newest_row():
    assert owner()({"name": "tests Z (z)"}) == (
        {"wo": "three", "M": "m3", "zones": ["C"], "overlapping": []}, {"wo": "three", "zone": "landed-three"})
    assert owner()({"name": "type check"})[0]["wo"] == "three"


def test_move_row_owns_its_findings_in_the_validation_zone():
    move = {"wo": "v54-move", "M": "mv", "move": True}
    found = recheck_owner([move], move, lambda name: "never", lambda wo: None, lambda name: "zone-of-" + name)
    assert found({"name": "suite"}) == (move, {"wo": "v54-move", "feature": "v54-move", "zone": "zone-of-suite"})
