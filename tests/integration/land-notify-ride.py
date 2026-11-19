#!/usr/bin/env python3
"""Team.notify renders ride options for detached notice commands."""
import importlib.machinery
import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_notify_ride", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def team_at(root, template=None):
    manifest = root / "sample.toml"
    manifest.write_text(f"repo = {json.dumps(str(root))}\nworktree_root = {json.dumps(str(root))}\n" +
                        (f"[land]\nnotify = {json.dumps(template)}\n" if template is not None else ""))
    return cl.Team(str(manifest), create=False)


def standin_at(root, ride_field):
    script = root / "standin.py"
    output = root / "argv.json"
    script.write_text("#!/usr/bin/env python3\n"
                      "import json, os, sys\n"
                      "from pathlib import Path\n"
                      "out = Path(sys.argv[1])\n"
                      "tmp = out.with_suffix('.tmp')\n"
                      "tmp.write_text(json.dumps(sys.argv[2:]))\n"
                      "os.replace(tmp, out)\n")
    script.chmod(0o755)
    template = f"{shlex.quote(str(script))} {shlex.quote(str(output))} {ride_field} {{kind}} {{to}} {{text}}"
    return team_at(root, template), output


def read_args(output):
    deadline = time.monotonic() + 5
    while not output.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert output.exists(), "detached stand-in did not write its arguments"
    return json.loads(output.read_text())


def test_custom_template_ride_true_passes_ride():
    with tempfile.TemporaryDirectory() as tmp:
        team, output = standin_at(Path(tmp), "{ride}")
        team.notify("lane name", "NOTE", "some text", ride=True)
        assert read_args(output) == ["--ride", "NOTE", "lane name", "some text"]


def test_custom_template_default_ride_has_no_empty_argument():
    with tempfile.TemporaryDirectory() as tmp:
        team, output = standin_at(Path(tmp), "{ride}")
        team.notify("lane name", "NOTE", "some text")
        assert read_args(output) == ["NOTE", "lane name", "some text"]


def test_custom_template_without_ride_still_sends_waking():
    with tempfile.TemporaryDirectory() as tmp:
        team, output = standin_at(Path(tmp), "")
        team.notify("lane name", "NOTE", "some text", ride=True)
        assert read_args(output) == ["NOTE", "lane name", "some text"]


def test_default_template_renders_ride_immediately_after_say():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        with patch.object(cl, "spawn") as spawn:
            team.notify("lane name", "NOTE", "some text", ride=True)
        spawn.assert_called_once()
        assert shlex.split(spawn.call_args.args[0]) == [
            str(ROOT / "v2" / "bin" / "codeteam2"), "say", "--ride", str(team.manifest),
            "general", "codeteam", "NOTE", "lane name", "some text",
        ]


if __name__ == "__main__":
    failed = 0
    for name, test in list(globals().items()):
        if not name.startswith("test_") or not callable(test):
            continue
        try:
            test()
            print(f"  PASS {name}")
        except (Exception, SystemExit) as exc:
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)
