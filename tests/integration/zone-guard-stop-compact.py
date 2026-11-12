#!/usr/bin/env -S python3 -u
"""zone-guard's stop hook runs compact-now when the handoff's last reply says 'Run /compact now', even when that reply
reaches the transcript after the hook has started (the reply was once written about
150 ms after the turn ended and /compact never ran). The real hook runs as a subprocess with HOME, codeteam's home and
the codeteam command all in a temp folder; a writer thread adds the reply while the hook waits."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "share" / "claude-hooks" / "zone-guard.py"
SID = "s-1"


def record(kind, text):
    if kind == "user":
        return json.dumps({"type": "user", "message": {"content": text}}) + "\n"
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n"


def run_stop(late_reply, state, given=None):
    """Run the stop hook; the turn's last reply is written late_reply seconds after it starts (None: before).
    Returns (compact-now called, state after)."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        home = d / "ct"
        (home / "run" / "ctx").mkdir(parents=True)
        (home / "teams").mkdir()
        (home / "teams" / "widgets.toml").write_text('product = "widgets"\n')
        called = d / "called"
        fake = d / "codeteam2"
        fake.write_text(f"#!/bin/sh\necho \"$@\" > {called}\n")
        fake.chmod(0o755)
        (home / "run" / "ctx" / "widgets-Kong.json").write_text(json.dumps(dict(state, session=SID)))
        tr = d / "t.jsonl"
        tr.write_text(record("user", "[codeteam] #1 REQUEST") + record("assistant", "Writing the handoff now."))
        reply = record("assistant", "Filed.\n\nReady. Run /compact now.")
        if late_reply is None:
            with tr.open("a") as f:
                f.write(reply)

        def write_late():
            time.sleep(late_reply)
            with tr.open("a") as f:
                f.write(reply)
        writer = threading.Thread(target=write_late) if late_reply is not None else None
        env = dict(os.environ, HOME=str(d), CODETEAM_SESSION="Kong", CODETEAM_HOME=str(home),
                   CODETEAM_MANIFEST=str(home / "teams" / "widgets.toml"), CODETEAM_BIN=str(fake))
        for k in ("CODETEAM_SWT", "CODETEAM_ZONE"):
            env.pop(k, None)
        stdin = {"transcript_path": str(tr), "session_id": SID, "stop_hook_active": False}
        if given is not None:
            stdin["last_assistant_message"] = given
        if writer:
            writer.start()
        subprocess.run([sys.executable, str(HOOK), "stop"], input=json.dumps(stdin), capture_output=True, text=True,
                       env=env, timeout=30)
        if writer:
            writer.join()
        for _ in range(20):                       # compact-now is started detached
            if called.exists():
                break
            time.sleep(0.1)
        return called.exists(), json.loads((home / "run" / "ctx" / "widgets-Kong.json").read_text())


def test_a_reply_already_written_runs_compact_now():
    called, state = run_stop(None, {"prompted": 1.0})
    assert called and state.get("compact_sent")


def test_a_reply_written_after_the_hook_starts_still_runs_compact_now():
    called, state = run_stop(0.6, {"prompted": 1.0})
    assert called and state.get("compact_sent"), state


def test_the_reply_given_in_the_hook_input_is_enough():
    called, _ = run_stop(5.0, {"prompted": 1.0}, given="Ready. Run /compact now.")
    assert called


def test_no_prompt_no_compact():
    called, _ = run_stop(None, {})
    assert not called


def test_compact_runs_once():
    called, _ = run_stop(None, {"prompted": 1.0, "compact_sent": 2.0})
    assert not called


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:          # report every case, then fail once
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
