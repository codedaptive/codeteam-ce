import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
import contextlib

from codeteam_recheck_at import recheck_at


class Failed(Exception):
    pass


def tracking():
    events = []

    @contextlib.contextmanager
    def lock():
        events.append("lock")
        yield
        events.append("unlock")
    return events, lock()


def test_checkout_and_run_happen_inside_the_lock():
    events, lock = tracking()
    def checkout():
        events.append("checkout")
        return Path("tree")
    def run(tree):
        events.append(f"run {tree}")
        return {"ran": str(tree)}
    assert recheck_at(lock, checkout, run, Failed, lambda ex: {"failed": True}) == {"ran": "tree"}
    assert events == ["lock", "checkout", "run tree", "unlock"]


def test_failed_checkout_gives_the_failed_result_and_runs_nothing():
    events, lock = tracking()
    def checkout():
        raise Failed("no tree")
    def run(tree):
        events.append("run")
        return {}
    assert recheck_at(lock, checkout, run, Failed, lambda ex: {"error": str(ex)}) == {"error": "no tree"}
    assert events == ["lock", "unlock"]
