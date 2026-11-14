"""The Host check every request passes first."""


def host_allowed(host: str | None, port: int) -> bool:
    """True only for Host 127.0.0.1:<port> or localhost:<port> (any case). A page on another name that resolves
    to 127.0.0.1 (DNS rebinding) sends its own name, so it is refused."""
    return host is not None and host.lower() in (f"127.0.0.1:{port}", f"localhost:{port}")
