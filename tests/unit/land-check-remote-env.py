#!/usr/bin/env -S python3 -u
"""Remote validation passes the landing environment to land-check over ssh."""
import importlib.machinery
import importlib.util
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


with patch("subprocess.run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader = importlib.machinery.SourceFileLoader(
        "cl_remote_env", str(Path(__file__).resolve().parents[2] / "bin" / "codeteam-land"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)


def no_command(*args, **kwargs):
    raise AssertionError(f"unexpected command: {args or kwargs}")


class RemoteLandingEnvironmentTests(unittest.TestCase):
    def test_remote_validation_disables_incremental(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "team.toml").write_text(
                f'repo = "{root / "repo"}"\nworktree_root = "{root / "work"}"\n'
                f'[env]\nTMPDIR = "{root / "tmp"}/"\nCARGO_INCREMENTAL = "1"\n')
            tier = {"host": "test-host", "path": "~/validation", "suite": "test-suite"}
            response = SimpleNamespace(stdout='{"hash": "abc123", "result": "pass"}\n',
                                       stderr="", returncode=0)
            with (patch.dict(os.environ, {"HOME": str(root / "home"),
                                          "CODETEAM_QUEUE_DIR": str(root / "queue")}),
                  patch("subprocess.run", side_effect=no_command),
                  patch("subprocess.Popen", side_effect=no_command),
                  patch.object(module, "toolchain_fp", return_value="fingerprint"),
                  patch.object(module, "ssh", return_value=response) as ssh):
                team = module.Team(str(root / "team.toml"), create=False)
                result = module.run_land_check(team, tier, "abc123", "validation")
            self.assertEqual(result, {"hash": "abc123", "result": "pass"})
            ssh.assert_called_once()
            self.assertEqual(ssh.call_args.args[0], tier)
            words = shlex.split(ssh.call_args.args[1])
            assignments = words[words.index("&&") + 1:words.index("~/bin/land-check")]
            self.assertIn("GROUP=validation", assignments)
            self.assertIn("CODETEAM_TEST_GROUP=validation", assignments)
            self.assertIn("CARGO_INCREMENTAL=0", assignments)

    def remote_command(self, value):
        team = SimpleNamespace(zones={}, cfg={}, m={"env": {"CODETEAM_KINDS_BY_NAME": value}})
        tier = {"host": "test-host", "path": "~/validation", "suite": "test-suite"}
        response = SimpleNamespace(stdout='{"hash":"abc123","result":"pass"}', stderr="", returncode=0)
        with patch.object(module, "toolchain_fp", return_value="fingerprint"), \
                patch.object(module, "toolchain_cmd", return_value=""), \
                patch.object(module, "ssh", return_value=response) as ssh:
            module.run_land_check(team, tier, "abc123", "validation")
        return ssh.call_args.args[1]

    def test_remote_kinds_on_is_forwarded(self):
        words = shlex.split(self.remote_command("1"))
        self.assertIn("CODETEAM_KINDS_BY_NAME=1", words[words.index("&&") + 1:words.index("~/bin/land-check")])

    def test_remote_kinds_off_command_is_unchanged(self):
        self.assertEqual(self.remote_command("0"),
            'cd "$HOME"/validation && LAND_KEEP=\'\' GROUP=validation CODETEAM_TEST_GROUP=validation '
            'CARGO_INCREMENTAL=0 CODETEAM_HANG_WINDOW=600 CODETEAM_HANG_CPU_PCT=1 '
            "~/bin/land-check abc123 test-suite '' fingerprint")


if __name__ == "__main__":
    unittest.main()
