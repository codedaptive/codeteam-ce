"""When a transcript last shows a model answering, after a given time.

A real answer is an `assistant` record whose message names a model; an API error is an assistant record too, but
with model `<synthetic>` and `isApiErrorMessage`, so neither of those counts.
"""
import datetime as dt


def succeeded_after(records, t: float) -> float | None:
    """The epoch seconds of the newest real model answer timestamped after `t`, in any record order, else None."""
    times = [dt.datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).timestamp()
             for r in records
             if r.get("type") == "assistant" and not r.get("isApiErrorMessage") and r.get("timestamp")
             and r.get("message", {}).get("model") not in (None, "", "<synthetic>")]
    return max((at for at in times if at > t), default=None)
