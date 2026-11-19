import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_batch_causes import batch_causes


def members(entry):
    return [(wo, "tip") for wo in entry["wos"]]


GROUP = [("p1", {"wos": ["a", "a2"], "files": ["shared", "src/a"]}),
         ("p2", {"wos": ["b"], "files": ["src/b"]}),
         ("p3", {"wos": ["c"], "files": ["shared"]}),
         ("p4", {"wos": ["d"], "files": ["shared"]})]


def test_names_every_member_of_earlier_entries_that_changed_a_conflicting_file():
    assert batch_causes(GROUP, "p4", ["shared"], set(), members) == ["a", "a2", "c"]


def test_skips_entries_that_conflicted_themselves_and_entries_after_the_key():
    assert batch_causes(GROUP, "p3", ["shared"], {"p1"}, members) == []


def test_first_entry_or_no_shared_file_has_no_cause():
    assert batch_causes(GROUP, "p1", ["shared"], set(), members) == []
    assert batch_causes(GROUP, "p4", ["other"], set(), members) == []
