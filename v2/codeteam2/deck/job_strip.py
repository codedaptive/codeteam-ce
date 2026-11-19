"""The job strip at the top of the deck's BUILDS box."""


def job_strip(running: int, queued: int, motion: bool) -> list[tuple[str, str]]:
    """One cell per job as two (text, colour) segments: running in green (with motion on and a job running, the
    "~sweep" word after it), then queued in faint. Whole: the caller cuts it to its box."""
    green = "green ~sweep" if motion and running else "green"
    return [("█" * running, green), ("█" * queued, "faint")]
