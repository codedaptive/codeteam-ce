"""The newest model answer on this machine after a given time, read from Claude Code's transcripts.

Every Claude Code session on the machine, of any team or none, writes its answers to ~/.claude/projects, so a
success there after an API error shows the service is answering again. The scan is kept small: only files modified
after the error can hold a later answer, the newest are read first, at most `max_files` of them, and only each
file's tail.
"""
from pathlib import Path

from .succeeded_after import succeeded_after
from .transcript_records import transcript_records

PATTERNS = ("*/*.jsonl", "*/*/subagents/**/agent-*.jsonl")     # main sessions, then their subagents at any depth


def newest_success(since: float, root=None, max_files: int = 200) -> float | None:
    """Epoch seconds of the newest real answer after `since` in the transcripts under `root` (default
    ~/.claude/projects), else None."""
    base = Path(root) if root else Path.home() / ".claude" / "projects"
    recent = []
    for pattern in PATTERNS:
        for path in base.glob(pattern):
            try:
                mtime = path.stat().st_mtime
            except OSError:     # removed between the listing and the stat
                continue
            if mtime > since:
                recent.append((mtime, path))
    recent.sort(reverse=True)
    found = [succeeded_after(transcript_records(path), since) for _, path in recent[:max_files]]
    return max((at for at in found if at is not None), default=None)
