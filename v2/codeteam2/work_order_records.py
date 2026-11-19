"""The landing tool's open work-order records (land/wo/<wo>.json), read once for the patrol's checks (D590)."""
import json
from pathlib import Path


def work_order_records(land_dir) -> list[dict]:
    """Each land_dir/wo/*.json record, in file-name order, that is a JSON object whose "tree", "zone" and "wo" are all
    strings, so its readers can use them as a path and names without checking. Landed and retired records, unreadable
    files, bad JSON and any other record are left out; no wo folder gives []."""
    out = []
    for f in sorted(Path(land_dir, "wo").glob("*.json")):
        if f.name.endswith((".landed.json", ".retired.json")):
            continue
        try:
            rec = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and all(isinstance(rec.get(k), str) for k in ("tree", "zone", "wo")):
            out.append(rec)
    return out
