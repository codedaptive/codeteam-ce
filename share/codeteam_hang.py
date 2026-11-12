"""Shared, conservative hang decisions for test process trees."""

from collections import defaultdict, deque
from collections.abc import Mapping
import ctypes
from functools import lru_cache
import math
import subprocess


WINDOW_ENV = "CODETEAM_HANG_WINDOW"
CPU_ENV = "CODETEAM_HANG_CPU_PCT"


def settings(env: Mapping[str, str]) -> tuple[float, float]:
    values = []
    for name, default in ((WINDOW_ENV, 600.0), (CPU_ENV, 1.0)):
        try:
            value = float(env.get(name, default))
        except ValueError:
            value = default
        values.append(value if math.isfinite(value) and value > 0 else default)
    return values[0], values[1]


def parse_cputime(text: str) -> float:
    """Read ps's [[dd-]hh:]mm:ss[.ss] CPU time in seconds."""
    days, sep, clock = text.strip().rpartition("-")
    seconds = 0.0
    for part in clock.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds + (int(days) * 86400 if sep else 0)


class _RusageInfoV2(ctypes.Structure):
    # Keep the full V2 layout: libproc writes the entire structure, including disk I/O fields.
    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in (
            "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups",
            "ri_pageins", "ri_wired_size", "ri_resident_size", "ri_phys_footprint",
            "ri_proc_start_abstime", "ri_proc_exit_abstime", "ri_child_user_time",
            "ri_child_system_time", "ri_child_pkg_idle_wkups", "ri_child_interrupt_wkups",
            "ri_child_pageins", "ri_child_elapsed_abstime", "ri_diskio_bytesread",
            "ri_diskio_byteswritten",
        )
    ]


class _MachTimebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


@lru_cache(maxsize=1)
def _rusage_api():
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
    libproc.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    libproc.proc_pid_rusage.restype = ctypes.c_int
    system = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    system.mach_timebase_info.argtypes = [ctypes.POINTER(_MachTimebase)]
    system.mach_timebase_info.restype = ctypes.c_int
    timebase = _MachTimebase()
    if system.mach_timebase_info(ctypes.byref(timebase)) != 0 or not timebase.denom:
        raise OSError("mach timebase unavailable")
    return libproc, timebase.numer / timebase.denom / 1e9


def _rusage_cpu(pid: int) -> float | None:
    """Own and reaped-children CPU seconds, or unknown if the native reader fails."""
    try:
        libproc, seconds_per_tick = _rusage_api()
        info = _RusageInfoV2()
        # RUSAGE_INFO_V2 includes reaped children, so workers between ps samples still count.
        if libproc.proc_pid_rusage(pid, 2, ctypes.byref(info)) != 0:
            return None
        return (info.ri_user_time + info.ri_system_time + info.ri_child_user_time
                + info.ri_child_system_time) * seconds_per_tick
    except Exception:
        # Sampling failure must never turn unknown progress into permission to kill.
        return None


def _process_table() -> dict[int, tuple[int, float]] | None:
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,time="],
                                 capture_output=True, text=True, check=True).stdout
        table = {}
        for line in listing.splitlines():
            pid, ppid, cpu = line.split()
            table[int(pid)] = (int(ppid), parse_cputime(cpu))
        return table
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def tree_cpu(root_pid: int, table: Mapping[int, tuple[int, float]] | None = None,
             exclude: tuple[int, ...] = ()) -> dict[int, float] | None:
    """Sample the root and live descendants, excluding each named pid's entire subtree."""
    if table is None:
        table = _process_table()
    if table is None or root_pid not in table:
        return None
    children = defaultdict(list)
    for pid, (ppid, _) in table.items():
        children[ppid].append(pid)
    cpu_by_pid = {}
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        if pid in exclude or pid in cpu_by_pid:
            continue
        cpu = _rusage_cpu(pid)
        if cpu is None:
            # An exiting child may not yet be accounted for by its parent: the whole sample is unknown.
            return None
        cpu_by_pid[pid] = cpu
        pending.extend(children[pid])
    return cpu_by_pid


class HangWatch:
    def __init__(self, window: float, cpu_pct: float, start: float, watch_output: bool = True):
        self.window = window
        self.cpu_pct = cpu_pct
        self.start = start
        self.watch_output = watch_output
        self.last_output = start
        self.previous: dict[int, float] = {}
        self.samples: deque[tuple[float, float | None]] = deque()

    def output(self, t: float) -> None:
        self.last_output = max(self.last_output, t)

    def sample(self, t: float, cpu_by_pid: Mapping[int, float] | None) -> None:
        delta = None
        if cpu_by_pid is not None:
            delta = sum(max(0, cpu - self.previous.get(pid, 0)) for pid, cpu in cpu_by_pid.items())
            self.previous = dict(cpu_by_pid)
        self.samples.append((t, delta))
        while self.samples and self.samples[0][0] <= t - self.window:
            self.samples.popleft()

    def hung(self, t: float) -> str | None:
        if t - self.start < self.window:
            return None
        silent = t - self.last_output
        if self.watch_output and silent < self.window:
            return None
        while self.samples and self.samples[0][0] <= t - self.window:
            self.samples.popleft()
        if not self.samples:
            return None
        used = 0.0
        for _, cpu in self.samples:
            if cpu is None:
                return None
            used += cpu
        threshold = self.window * self.cpu_pct / 100
        if used >= threshold:
            return None
        return (f"hung: silent for {silent:.1f} s; tree CPU {used:.3f} s over {self.window:g} s "
                f"is below {threshold:.3f} s ({self.cpu_pct:g}%)")
