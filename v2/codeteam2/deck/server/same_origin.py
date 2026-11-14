"""The Origin check for the one request that acts (POST /disk-now)."""


def same_origin(origin: str | None, port: int) -> bool:
    """True only for Origin http://127.0.0.1:<port> or http://localhost:<port> (host in any case). A missing
    Origin, "null", https and any other host or port are refused, so another site's page cannot press disk-now."""
    if origin is None:
        return False
    scheme, sep, host = origin.partition("://")
    return sep == "://" and scheme == "http" and host.lower() in (f"127.0.0.1:{port}", f"localhost:{port}")
