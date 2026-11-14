"""`codeteam2 deck --web`: the collector thread plus the server, until Ctrl-C."""
import errno
import threading
from pathlib import Path

from .build_server import build_server
from .collector import Collector

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def serve(names, *, port, interval, thresholds, motion_on, out=print, web_dir=None) -> int:
    """Serve the deck at http://127.0.0.1:<port>/ until Ctrl-C (0). A port that is taken or not allowed prints one
    line naming --port and returns 1 before anything is collected."""
    collector = Collector(names, interval, thresholds)
    try:
        server = build_server(collector, port=port, web_dir=WEB_DIR if web_dir is None else web_dir,
                              motion_on=motion_on, interval=interval)
    except OSError as e:
        if e.errno not in (errno.EADDRINUSE, errno.EACCES):
            raise
        out(f"codeteam2 deck: port {port} is busy; choose another with --port")
        return 1
    threading.Thread(target=collector.run, name="deck-web-collect", daemon=True).start()
    out(f"http://127.0.0.1:{server.server_address[1]}/")      # the port bound: --port 0 takes any free one
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        collector.stop()
    return 0
