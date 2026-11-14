"""What route() decides for one request."""
from typing import NamedTuple


class Route(NamedTuple):
    """status: the HTTP status to answer; action: "page", "snapshot", "static", "disk_now" or "refuse";
    arg: the web file to serve for "page" and "static", else None."""
    status: int
    action: str
    arg: str | None
