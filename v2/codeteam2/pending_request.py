"""The model request a transcript is still waiting on, if any.

Claude Code writes an `api-request` record before every model call; the answer is an `assistant` record whose
`requestRef` names it, an API error is an `assistant` record too, and an interrupt or a tool result is a `user`
record, and an ended turn a `system` one. So a request is pending only while no user, assistant or system record
follows it. A running tool (a long build, a blocking watch) ends on an `assistant` tool_use record with no request
after it, which is why a tool call never reads as a hung request. The other record types (api-request-blob,
api-request-shape, attachment, progress, queue-operation, file-history-snapshot) are written around a call and
change nothing.
"""
import datetime as dt

ENDS_REQUEST = ("user", "assistant", "system")


def pending_request(records) -> dict | None:
    """{"id", "at" (epoch seconds), "model"} of the last `api-request` when nothing answered it, else None."""
    for record in reversed(records):
        kind = record.get("type")
        if kind in ENDS_REQUEST:
            return None
        if kind == "api-request":
            return {"id": record.get("id"),
                    "at": dt.datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp(),
                    "model": record.get("params", {}).get("model", "")}
    return None
