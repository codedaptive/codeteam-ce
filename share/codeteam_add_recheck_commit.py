"""Add a recheck's landing commit to an open test finding.

A test that still fails at a later recheck adds that recheck's M to its finding's "Ms", once. With batching, one
recheck covers a whole batch, so the M added is the batch's newest landing commit M*.
"""


def add_recheck_commit(items: list[dict], fid: str, M: str) -> bool:
    """Append M to the "Ms" of the item whose "id" is fid, unless it is there; True when items changed."""
    item = next(item for item in items if item["id"] == fid)
    if M in item["Ms"]:
        return False
    item["Ms"].append(M)
    return True
