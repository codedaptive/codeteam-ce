import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_validation_log import validation_log


def test_local_log_path():
    assert validation_log({"local": True}, "abc") == "~/land-check-logs/abc.log"


def test_remote_log_path_includes_host():
    assert validation_log({"host": "val"}, "abc") == "val:~/land-check-logs/abc.log"
