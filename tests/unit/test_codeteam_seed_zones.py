import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_seed_zones import seed_zones


SEED = {"name": "own", "path": "A/own.rs"}
ERROR = {"interface_error": "codegraph callers own: incomplete answer, calling zones may be missing"}


def zones(path):
    return {"A/own.rs": "A", "B/caller.rs": "B", "C/caller.rs": "C"}.get(path)


def complete():
    return {"callers": [{"path": "C/caller.rs"}, {"file": "B/caller.rs"}, {"filePath": "A/own.rs"},
                        {"path": "B/caller.rs"}, {"path": "unknown"}],
            "total": 5, "truncated": False,
            "definitions": [{"callers": [{"filePath": "B/caller.rs"}], "total": 1, "truncated": False}]}


def test_command_requests_full_limit():
    run = Mock(return_value=json.dumps(complete()))
    seed_zones("cg", "/tree", SEED, zones, "A", run=run)
    run.assert_called_once_with(["cg", "callers", "own", "-f", "A/own.rs", "-p", "/tree", "-j", "-l", "10000"])


def test_complete_answer_zones_are_sorted_filtered_and_deduplicated():
    run = Mock(return_value=json.dumps(complete()))
    assert seed_zones("cg", "/tree", SEED, zones, "A", run=run) == ({"B": ["B/caller.rs"], "C": ["C/caller.rs"]}, {})


def test_caller_files_within_a_zone_are_sorted_and_unique():
    answer = {"callers": [{"path": "B/z.rs"}, {"path": "B/a.rs"}, {"path": "B/z.rs"}],
              "total": 3, "truncated": False, "definitions": []}
    assert seed_zones("cg", "/tree", SEED, lambda path: "B", "A",
                      run=Mock(return_value=json.dumps(answer))) == ({"B": ["B/a.rs", "B/z.rs"]}, {})


def test_truncated_answer_retains_zones_and_reports_incomplete():
    data = complete()
    data["truncated"] = True
    data["total"] = 300
    run = Mock(return_value=json.dumps(data))
    assert seed_zones("cg", "/tree", SEED, zones, "A", run=run) == ({"B": ["B/caller.rs"], "C": ["C/caller.rs"]}, ERROR)


def test_short_definition_retains_zones_and_reports_incomplete():
    data = complete()
    data["definitions"][0]["total"] = 2
    run = Mock(return_value=json.dumps(data))
    assert seed_zones("cg", "/tree", SEED, zones, "A", run=run) == ({"B": ["B/caller.rs"], "C": ["C/caller.rs"]}, ERROR)


def test_null_answer_is_incomplete():
    assert seed_zones("cg", "/tree", SEED, zones, "A", run=Mock(return_value="null")) == ({}, ERROR)


def test_timeout_reports_exception():
    run = Mock(side_effect=subprocess.TimeoutExpired("cg", 60))
    assert seed_zones("cg", "/tree", SEED, zones, "A", run=run) == (
        {}, {"interface_error": "codegraph callers own: TimeoutExpired"})


def test_bad_json_reports_exception():
    assert seed_zones("cg", "/tree", SEED, zones, "A", run=Mock(return_value="not json")) == (
        {}, {"interface_error": "codegraph callers own: JSONDecodeError"})
