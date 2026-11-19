"""The class chips of the deck's BUILDS box."""
from collections.abc import Callable


def class_chips(classes: list[dict], number: Callable[[object], str],
                dicts: Callable[[object], list]) -> list[list[tuple[str, str]]]:
    """One chip per class: its name ("?" when it has none) teal bold, then " <running>/<ceiling>" dim, where
    running counts the dicts(c["running"]) jobs and a ceiling of 0 (no ceiling) shows as ∞, any other through
    number. number and dicts are the renderer's own readers, so a chip reads a class as every other BUILDS row does."""
    return [[(str(c.get("class") or "?"), "teal bold"),
             (f" {len(dicts(c.get('running')))}/{'∞' if c.get('ceiling') == 0 else number(c.get('ceiling'))}", "dim")]
            for c in classes]
