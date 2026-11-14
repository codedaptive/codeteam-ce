"""The listening socket."""
import errno
import socket
from http.server import ThreadingHTTPServer
from pathlib import Path

from .handler import make_handler

# How long the busy check waits for something already answering on the port.
PROBE_S = 0.5


def build_server(collector, *, port: int, web_dir: Path, motion_on: bool, interval: float) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1:<port> only (port 0: any free port), one daemon thread per request
    (ThreadingHTTPServer's daemon_threads). It keeps the stdlib's SO_REUSEADDR, so a restart right after Ctrl-C
    binds; on macOS that also lets it bind 127.0.0.1 under a program listening on 0.0.0.0:<port>, so a port that
    something already answers on at 127.0.0.1 raises OSError(EADDRINUSE) first. Bind errors raise as bind raises
    them."""
    if port and _answers(port):
        raise OSError(errno.EADDRINUSE, f"something already answers on 127.0.0.1:{port}")
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(collector, web_dir, motion_on, interval))


def _answers(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=PROBE_S).close()
    except OSError:  # ConnectionRefusedError and timeouts alike: nothing answers, so bind
        return False
    return True
