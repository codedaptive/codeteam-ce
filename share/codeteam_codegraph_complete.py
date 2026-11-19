"""Whether a CodeGraph callers or callees answer is whole, and the limit every such query asks for.

`codegraph callers -j` and `codegraph callees -j` answer one object holding the symbol's list under "callers" or
"callees", a "total", a "limit" and a "truncated" flag, plus a "definitions" list whose every entry carries the same
four fields. The answer is whole when the top level and every definition say "truncated" exactly False, have an int
"total" (not a bool) and a list under the key at least that long.
"""

# codeteam-jj's bound, far above any real symbol's callee or caller count, so an answer asked with it is not expected
# to be truncated (codegraph_complete still checks).
CODEGRAPH_LIMIT = 10000


def _whole(node, key: str) -> bool:
    return (isinstance(node, dict) and node.get("truncated") is False and type(node.get("total")) is int
            and isinstance(node.get(key), list) and len(node[key]) >= node["total"])


def codegraph_complete(answer, key: str) -> bool:
    """answer (parsed JSON) lists every entry under key, at the top level and in each of its "definitions"."""
    return (_whole(answer, key) and isinstance(answer.get("definitions"), list)
            and all(_whole(node, key) for node in answer["definitions"]))
