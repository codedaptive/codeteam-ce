"""The body of GET /snapshot.json."""
import json


def snapshot_payload(snap: dict, alerts: list) -> bytes:
    """UTF-8 JSON of the snapshot (every key as `codeteam2 deck --json` prints it) plus alert_log, the alerts the
    session has kept (model.AlertLog's list, as the terminal shows them)."""
    return json.dumps({**snap, "alert_log": alerts}, ensure_ascii=False).encode("utf-8")
