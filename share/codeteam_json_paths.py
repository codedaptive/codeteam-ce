"""Every file path in a parsed CodeGraph JSON answer."""


def json_paths(obj):
    """Yield, in document order, each string value of a "path", "file" or "filePath" key anywhere in obj."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("path", "file", "filePath") and isinstance(v, str):
                yield v
            else:
                yield from json_paths(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from json_paths(v)
