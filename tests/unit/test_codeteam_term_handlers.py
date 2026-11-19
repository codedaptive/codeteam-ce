import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_term_handlers import term_handlers


def handler(signum, frame):
    pass


def previous(signum, frame):
    pass


def test_main_thread_sets_both_handlers_for_the_block_and_restores_them():
    saved = {sig: signal.signal(sig, previous) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        with term_handlers(handler):
            assert signal.getsignal(signal.SIGTERM) is handler
            assert signal.getsignal(signal.SIGHUP) is handler
        assert signal.getsignal(signal.SIGTERM) is previous
        assert signal.getsignal(signal.SIGHUP) is previous
    finally:
        for sig, old in saved.items():
            signal.signal(sig, old)


def test_handlers_are_restored_when_the_block_raises():
    saved = signal.signal(signal.SIGTERM, previous)
    try:
        try:
            with term_handlers(handler):
                raise SystemExit(143)
        except SystemExit:
            pass
        assert signal.getsignal(signal.SIGTERM) is previous
    finally:
        signal.signal(signal.SIGTERM, saved)


def test_another_thread_runs_the_block_without_touching_handlers():
    seen = []

    def body():
        with term_handlers(handler):
            seen.append(signal.getsignal(signal.SIGTERM))

    before = signal.getsignal(signal.SIGTERM)
    thread = threading.Thread(target=body)
    thread.start()
    thread.join()
    assert seen == [before]
