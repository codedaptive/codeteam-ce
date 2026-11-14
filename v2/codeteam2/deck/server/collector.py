"""The web deck's one collector: the terminal deck's refresh, run on its own thread for every tab at once."""
import threading
import time
import traceback

from .. import app, collect, model

# Seconds without a request after which the collector stops collecting until the next one.
IDLE_S = 30.0


class Collector:
    """Runs app._refresh and app._follow_teams every `interval` seconds, as the terminal deck's loop does, while a
    tab has asked for the snapshot in the last IDLE_S seconds. Tabs only read the latest pair, so any number of them
    costs one collect per interval. Every scanner call happens on the collector's thread."""

    def __init__(self, names, interval, thresholds, *, collect_mod=None, scanner=None, clock=time.time):
        collect_mod = collect if collect_mod is None else collect_mod
        self.names, self.interval, self.thresholds = names, interval, thresholds
        self.collect_mod, self.clock = collect_mod, clock
        self.scanner = scanner if scanner is not None else collect_mod.DiskScanner({})
        self.cache = collect_mod.Cache()
        self.alert_log = model.AlertLog()
        self.pair = ({}, [])
        # Starts "just asked", so the server collects right after it starts.
        self.last_request = clock()
        self._disk_pending = False
        self._stopped = False
        self._wake = threading.Event()
        # The idle decision and a request's wake are one handshake under _lock: tick() marks _sleeping when it goes
        # idle, and the next request clears it and wakes the thread. Deciding "idle" from timestamps on both sides
        # could leave the thread waiting forever while every request saw "active".
        self._lock = threading.Lock()
        self._sleeping = False

    def active(self, now: float) -> bool:
        return now - self.last_request < IDLE_S

    def tick(self, now: float) -> bool:
        """One refresh when active (True). When idle, empty the scanner's roots so its passes measure nothing
        (app._follow_teams puts them back on the next active tick) and return False."""
        with self._lock:
            if not self.active(now):
                self._sleeping = True
                self.scanner.roots = {}
                return False
        self.pair = app._refresh(self.collect_mod, self.names, self.cache, self.thresholds, self.alert_log,
                                 self.pair, self.scanner.result())
        app._follow_teams(self.scanner, self.pair[0])
        if self._disk_pending:
            self._disk_pending = False
            self.scanner.scan_now()
        return True

    def latest(self, now: float | None = None) -> tuple:
        """The latest (snapshot, alerts). Records the request; wakes an idle collector, never collects itself."""
        self._request(self.clock() if now is None else now)
        return self.pair

    def disk_now(self) -> None:
        """The terminal's `d`: the next tick asks the scanner for a pass now. Counts as a request, so it also wakes
        an idle collector and is not lost."""
        self._disk_pending = True
        self._request(self.clock())

    def _request(self, now: float) -> None:
        """Stamp a request; wake the thread only when tick() has put it to sleep, so polls never add collects."""
        with self._lock:
            self.last_request = now
            if self._sleeping:
                self._sleeping = False
                self._wake.set()

    def run(self) -> None:
        """Tick until stop(): wait `interval` after a collect (or a tick that raised), and until the next request
        or stop() when idle. A tick that raises is logged and the loop goes on."""
        while not self._stopped:
            self._wake.clear()
            try:
                collected = self.tick(self.clock())
            except Exception:  # the server outlives any one bad tick
                app._log(traceback.format_exc())
                collected = True
            if self._stopped:
                return
            self._wake.wait(self.interval if collected else None)

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()
