"""The recoverable API error a transcript's last turn ended on, if any.

Claude Code writes an API error as an `assistant` record with `isApiErrorMessage`, model `<synthetic>` and its kind
in `error`. The turn ended on it when no `user` or `assistant` record follows it: a later user record is a new
prompt, a later assistant one an answer. Other record types (system, progress, attachment, ...) change nothing.
"""
import datetime as dt

from .recoverable_errors import RECOVERABLE


def last_api_error(records) -> tuple[str, float, str] | None:
    """(kind, epoch seconds, record uuid) when the last user or assistant record is a RECOVERABLE API error."""
    for record in reversed(records):
        if record.get("type") not in ("user", "assistant"):
            continue
        if record["type"] != "assistant" or not record.get("isApiErrorMessage") \
                or record.get("error") not in RECOVERABLE:
            return None
        return (record["error"], dt.datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp(),
                record.get("uuid"))
    return None
