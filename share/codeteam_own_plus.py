"""The added lines a work order made itself, out of a blast against a merged base."""


def own_plus(plus: dict, own: dict | None) -> dict:
    """plus with each path's lines cut to those also in own; plus unchanged when own is None (no own diff)."""
    if own is None:
        return plus
    return {path: lines & own.get(path, set()) for path, lines in plus.items()}
