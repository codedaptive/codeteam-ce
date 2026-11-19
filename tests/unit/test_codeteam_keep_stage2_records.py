import copy
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_keep_stage2_records import keep_stage2_records


def test_copies_unique_names_drops_missing_and_does_not_mutate(tmp_path):
    a = tmp_path / "a" / ".test-record.json"
    b = tmp_path / "b" / ".test-record.json"
    a.parent.mkdir(); b.parent.mkdir()
    a.write_text("first"); b.write_text("second")
    rows = [{"step": "tests A (a)", "records": [str(a), str(tmp_path / "missing")]},
            {"step": "tests B (b)", "records": [str(b)]}, {"step": "compile"}]
    original = copy.deepcopy(rows)
    kept = keep_stage2_records(tmp_path / "land", "wo", rows)
    folder = tmp_path / "land" / "stage2-records" / "wo"
    assert kept == [{"step": "tests A (a)", "records": [str(folder / "00-tests-A-a-.test-record.json")]},
                    {"step": "tests B (b)", "records": [str(folder / "01-tests-B-b-.test-record.json")]},
                    {"step": "compile"}]
    assert (folder / "00-tests-A-a-.test-record.json").read_text() == "first"
    assert (folder / "01-tests-B-b-.test-record.json").read_text() == "second"
    assert rows == original


def test_copy_error_preserves_row_and_reports_error(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("test")
    rows = [{"step": "tests A", "records": [str(source)]}]
    with patch("shutil.copy2", side_effect=OSError("disk full")), patch("shutil.copyfile", side_effect=OSError("disk full")):
        kept = keep_stage2_records(tmp_path / "land", "wo", rows)
    assert kept == [{"step": "tests A", "records": [str(source)], "records_error": "OSError: disk full"}]
    assert rows == [{"step": "tests A", "records": [str(source)]}]


def test_same_file_is_not_copied_onto_itself(tmp_path):
    folder = tmp_path / "stage2-records" / "wo"
    folder.mkdir(parents=True)
    source = folder / "00-tests-A-.test-record.json"
    source.write_text("kept")
    rows = [{"step": "tests A", "records": [str(source)]}]
    assert keep_stage2_records(tmp_path, "wo", rows) == rows
    assert source.read_text() == "kept"


def test_keeps_newest_200_folders_but_never_removes_current(tmp_path):
    folder = tmp_path / "stage2-records"
    folder.mkdir()
    for i in range(201):
        old = folder / f"old-{i:03d}"
        old.mkdir()
        os.utime(old, (1000 + i, 1000 + i))
    current = folder / "current"
    current.mkdir()
    os.utime(current, (1, 1))
    source = tmp_path / "source.json"
    source.write_text("data")
    keep_stage2_records(tmp_path, "current", [{"step": "tests A", "records": [str(source)]}])
    assert current.exists()
    assert len(list(folder.iterdir())) == 200
    assert not (folder / "old-000").exists()
