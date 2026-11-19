"""SIGTERM and SIGHUP handlers for one block (codeteam-land's `land`; D382, D394).

A stopped land must still run its finally blocks (the set's first tree back on its branch, every record saved), so
`land` turns both signals into an exit for its run. Only the main thread may set a handler; elsewhere the block runs
with the handlers as they are.
"""

import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager


@contextmanager
def term_handlers(handler: Callable) -> Iterator[None]:
    """On the main thread, handler for SIGTERM and SIGHUP during the block, the previous handlers back after it."""
    main = threading.current_thread() is threading.main_thread()
    previous = {sig: signal.signal(sig, handler) for sig in (signal.SIGTERM, signal.SIGHUP)} if main else {}
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)
