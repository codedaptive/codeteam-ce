import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_failure_frames import failure_frames


@pytest.mark.parametrize("text", [
    'File "src/a.py", line 12, in f',
    'src/a.py:12: AssertionError',
    '  --> src/a.py:12:5',
    'panicked at src/a.py:12:5:',
])
def test_recognizes_failure_frame_forms(tmp_path, text):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("")
    assert failure_frames(text, tmp_path) == [["src/a.py", 12]]


def test_absolute_path_inside_tree_is_made_relative(tmp_path):
    (tmp_path / "A.swift").write_text("")
    text = f"{tmp_path}/A.swift:7:3: error: failure"
    assert failure_frames(text, tmp_path) == [["A.swift", 7]]


def test_external_and_missing_files_are_dropped(tmp_path):
    external = tmp_path.parent / (tmp_path.name + "-outside.py")
    external.write_text("")
    try:
        assert failure_frames(f'{external}:2: error\nmissing.py:3: error', tmp_path) == []
    finally:
        external.unlink()


def test_frames_are_deduplicated_in_output_order(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    text = 'b.py:4: error\na.py:3: error\nb.py:4:5: error\na.py:8: error'
    assert failure_frames(text, tmp_path) == [["b.py", 4], ["a.py", 3], ["a.py", 8]]
