"""keep_stage2_records: copy a landing's Stage 2 test records into land/ (codeteam-jj #4664 item 3, D554).

A Stage 2 step's zone-test records live in the tree it ran in, which the landing removes, or in the shared itest
tree, which the next run writes over. A slow follow-up compares stages from them, so the landing copies each step's
records to land/stage2-records/<key>/ and its rows name the copies, the way keep_recheck_logs keeps a recheck's
logs. A copy that fails keeps the row's own paths and says why; it never stops a landing.
"""
import re
import shutil
from pathlib import Path

STAGE2_RECORDS_KEPT = 200       # folders kept, the newest by mtime; older ones are removed


def keep_stage2_records(land_dir: str | Path, key: str, rows: list[dict]) -> list[dict]:
    """New rows whose "records" name copies under land_dir/stage2-records/key/, each named
    "<row index>-<step slug>-<file name>"; a record file that no longer exists is dropped, a row without "records"
    comes back equal, and a row whose copy fails keeps its paths and gains "records_error". The rows given are not
    changed. Keeps the newest STAGE2_RECORDS_KEPT folders, never key's own. Never raises."""
    root = Path(land_dir) / "stage2-records"
    kept = [_keep_row(root / key, index, row) for index, row in enumerate(rows)]
    _prune(root, root / key)
    return kept


def _keep_row(folder: Path, index: int, row: dict) -> dict:
    """row with its existing records copied into folder; on a copy error, its own paths and "records_error"."""
    if "records" not in row:
        return dict(row)
    try:
        return dict(row, records=[_copy(folder, index, row.get("step", ""), Path(path))
                                  for path in row["records"] if Path(path).is_file()])
    except OSError as ex:
        return dict(row, records=list(row["records"]), records_error=f"{type(ex).__name__}: {ex}")


def _copy(folder: Path, index: int, step: str, source: Path) -> str:
    """The kept copy's path; a source already in folder is the copy (rows kept once already)."""
    if source.parent.resolve() == folder.resolve():
        return str(source)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{index:02d}-{re.sub(r'[^A-Za-z0-9._-]+', '-', step).strip('-')}-{source.name}"
    shutil.copy2(source, target)
    return str(target)


def _prune(root: Path, current: Path) -> None:
    """Remove all but the newest STAGE2_RECORDS_KEPT folders under root, counting current, which stays."""
    try:
        others = sorted((path for path in root.iterdir() if path.is_dir() and path != current),
                        key=lambda path: path.stat().st_mtime, reverse=True)
        keep = STAGE2_RECORDS_KEPT - 1 if current.is_dir() else STAGE2_RECORDS_KEPT
        for old in others[keep:]:
            shutil.rmtree(old)
    except OSError:     # retention is housekeeping: a landing's records stand without it
        pass
