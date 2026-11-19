"""build_part: the `, build B s` a done job's line carries inside its parentheses (R-26, D585).

A record whose build_seconds is a number (a bool is not one) gives `, build B s` with B in whole seconds; anything
else (no record, not a dict, no key, another type) gives "", so the line reads as it would without a build.
"""


def build_part(record: object) -> str:
    build = record.get("build_seconds") if isinstance(record, dict) else None
    if isinstance(build, bool) or not isinstance(build, (int, float)):
        return ""
    return f", build {build:.0f} s"
