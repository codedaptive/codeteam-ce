"""The parsed records at the end of a Claude Code transcript.

The loop reads many transcripts every pass (each session's and its recent subagents'), and a long session's file
runs to many megabytes, so only the tail is read: the questions asked of it (is a model request pending, how did the
last turn end) are answered by its last records.
"""
import json
import os


def transcript_records(path, tail=262144) -> list[dict]:
    """The JSON records in the last `tail` bytes of the transcript at `path`, in file order. A line cut by the tail's
    start is dropped, as is any line that is not JSON (a record still being written). An unreadable file gives []."""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - tail))
            data = f.read()
    except OSError:
        return []
    lines = data.split(b"\n")
    if size > tail:
        lines = lines[1:]
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records
