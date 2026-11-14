"""The deck server's whole route table."""
from collections.abc import Collection, Mapping

from .host_allowed import host_allowed
from .route_result import Route
from .same_origin import same_origin

# The GET-only routes besides the static files: path -> (action, arg).
_PAGES = {"/": ("page", "index.html"), "/snapshot.json": ("snapshot", None)}
# The page's template is served only filled in, at "/".
_TEMPLATE = "index.html"


def route(method: str, path: str, headers: Mapping, port: int, static_names: Collection[str]) -> Route:
    """The answer to one request. A Host other than 127.0.0.1:<port> or localhost:<port> is 403 before anything
    else; the query string and fragment are ignored; a known path asked with the wrong method is 405; POST
    /disk-now needs a same-origin Origin (else 403); a static file is served only by its exact name in
    static_names (so no path can reach outside the web folder); anything else is 404."""
    if not host_allowed(headers.get("Host"), port):
        return Route(403, "refuse", None)
    path = path.partition("?")[0].partition("#")[0]
    if path == "/disk-now":
        if method != "POST":
            return Route(405, "refuse", None)
        return Route(204, "disk_now", None) if same_origin(headers.get("Origin"), port) else Route(403, "refuse", None)
    name = path[1:]
    if path in _PAGES:
        action, arg = _PAGES[path]
    elif name in static_names and name != _TEMPLATE:
        action, arg = "static", name
    else:
        return Route(404, "refuse", None)
    return Route(200, action, arg) if method == "GET" else Route(405, "refuse", None)
