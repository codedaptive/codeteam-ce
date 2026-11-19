"""Move a work order's tip to its doc-fix commit in every record that holds it.

"Only changes to code go back through the entire process." A doc-fix commit keeps the work order's Stage 2 pass, so
the new commit replaces the old tip where it was recorded: the work order record (`tip`, `files` gains new files,
`doc_fixes` lists the commit), its queue entry (`tip`, or its member in a set's `tips`), its Stage 3 review row, and
its set partners' review rows' `with` items. Everything else (stage2, zones, reach, the owed integration step, the
queue place, the review's seen, reviewers and commits) is kept. The caller has checked the tip; a record that does not
hold `old` is a bug, so it raises ValueError before changing anything.
"""


def _entry_holds(entry: dict, wo: str, old: str) -> bool:
    if "tips" in entry:
        return [wo, old] in entry["tips"]
    return entry.get("wo") == wo and entry.get("tip") == old


def _move_entry(entry: dict, wo: str, old: str, new: str) -> None:
    if "tips" in entry:
        entry["tips"] = [[wo, new] if member == [wo, old] else member for member in entry["tips"]]
    if entry.get("wo") == wo and entry.get("tip") == old:
        entry["tip"] = new


def move_doc_fix_tip(rec: dict, entry: dict, row: dict, partner_rows: list[dict],
                     old: str, new: str, new_files: list[str]) -> None:
    """Rewrite tip `old` to `new` for work order `rec` in rec, entry, row and partner_rows, in place."""
    wo = rec["wo"]
    if rec.get("tip") != old or row.get("tip") != old or not _entry_holds(entry, wo, old):
        raise ValueError(f"{wo}: a record does not hold tip {old}")
    rec["tip"] = new
    files = rec.setdefault("files", [])
    for path in new_files:
        if path not in files:
            files.append(path)
    rec.setdefault("doc_fixes", []).append(new)
    _move_entry(entry, wo, old, new)
    row["tip"] = new
    for partner in partner_rows:
        for item in partner.get("with", []):
            if item.get("wo") == wo:
                item["tip"] = new
