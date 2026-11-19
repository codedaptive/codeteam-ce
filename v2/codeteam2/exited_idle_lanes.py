"""The lanes an idle stop marked whose exit the loop now sees, and whether each is cleaned (D598, D599).

Typing /exit does not end a lane: Runtime.confirm_exit cancels the exit when background work runs (D436), and the
lane goes on working in its tree. So an idle stop only marks the lane (clean_on_exit), the cancel clears the mark,
and the tree is cleaned on the tick that sees a marked lane gone: absent, or missing from the observation.
A marked lane with mail waiting for it at that tick is not idle: the mail starts it again (at once, or when the
change a held message waits for comes), and a detached clean could remove output the new session's first build needs. So its mark is cleared and it is not
cleaned (D599).
"""
from collections.abc import Collection, Mapping


def exited_idle_lanes(status: Mapping[str, str], st: Mapping[str, Mapping],
                      mail: Collection[str]) -> list[tuple[str, bool]]:
    """(key, clean) for each key marked clean_on_exit whose status is absent (a key missing from status counts as
    absent), sorted by key; clean is False when the key has mail waiting."""
    return sorted((k, k not in mail) for k, rec in st.items()
                  if rec.get("clean_on_exit") and status.get(k, "absent") == "absent")
