"""Shared, bounded launchd bootout waits and bootstrap retries."""

from dataclasses import dataclass
import subprocess
import time


# Bootout is asynchronous; an early bootstrap can fail with "5: Input/output error"
# (seen 2026-11-10). Bound the unload polls and pause before one bootstrap retry.
POLLS = 100
POLL_S = 0.2
RETRY_S = 2.0


@dataclass(frozen=True)
class ReinstallResult:
    installed: bool
    reason: str | None = None


def _launchctl(argv, run, timeout):
    if timeout is None:
        return run(argv, capture_output=True, text=True)
    return run(argv, capture_output=True, text=True, timeout=timeout)


def wait_for_bootout(target: str, *, run=None, sleep=None, polls: int = POLLS,
                     poll_s: float = POLL_S, timeout: float | None = None) -> bool:
    """Treat a non-zero print as unloaded; sleep only between prints."""
    run = run or subprocess.run
    sleep = sleep or time.sleep
    for attempt in range(polls):
        if _launchctl(["launchctl", "print", target], run, timeout).returncode:
            return True
        if attempt < polls - 1:
            sleep(poll_s)
    return False


def bootstrap(domain: str, plist, *, run=None, sleep=None, retry_s: float = RETRY_S,
              timeout: float | None = None) -> str | None:
    """Return None on success, or the second failure's stripped stderr."""
    run = run or subprocess.run
    sleep = sleep or time.sleep
    result = _launchctl(["launchctl", "bootstrap", domain, str(plist)], run, timeout)
    if result.returncode == 0:
        return None
    sleep(retry_s)
    result = _launchctl(["launchctl", "bootstrap", domain, str(plist)], run, timeout)
    if result.returncode == 0:
        return None
    return (result.stderr or "").strip()


def reinstall(label: str, plist, uid: int, *, run=None, sleep=None,
              wait_s: float = 20.0, poll_s: float = POLL_S, retry_s: float = RETRY_S,
              timeout: float | None = None) -> ReinstallResult:
    """Boot out and reload a job, withholding bootstrap if no print returns non-zero."""
    run = run or subprocess.run
    sleep = sleep or time.sleep
    target = f"gui/{uid}/{label}"
    _launchctl(["launchctl", "bootout", target], run, timeout)
    if not wait_for_bootout(target, run=run, sleep=sleep, polls=round(wait_s / poll_s),
                            poll_s=poll_s, timeout=timeout):
        return ReinstallResult(False, f"still loaded {wait_s:g} s after bootout; not reinstalled")
    error = bootstrap(f"gui/{uid}", plist, run=run, sleep=sleep, retry_s=retry_s, timeout=timeout)
    if error is not None:
        return ReinstallResult(False, f"launchctl bootstrap failed: {error}")
    return ReinstallResult(True)
