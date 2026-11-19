"""Whether the deck's BUILDS box has anything to show."""


def build_shown(running: list, queued: list, waits: list, runner: dict, warms: list) -> bool:
    """True when there are running or queued jobs, class wait rows, a live runner or warms."""
    return bool(running or queued or waits or runner.get("state") == "live" or warms)
