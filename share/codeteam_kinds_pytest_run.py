"""with_kinds: zone-tool test-one's pytest command and children's environment for a by-name run (V55-25 item 1).

With CODETEAM_KINDS_BY_NAME=1, pytest loads the codeteam_kinds_pytest plugin with --codeteam-kind=<group>. The
plugin lives in codeteam's share folder (this module's own folder), so that folder goes first on the children's
PYTHONPATH, ahead of any inherited entries, so a same-named module elsewhere cannot shadow it.
"""
import os
from collections.abc import Mapping
from pathlib import Path

SHARE = str(Path(__file__).resolve().parent)
# zone-tool builds its pytest command with this option last before the path; the plugin's options follow it.
AFTER = "no:cacheprovider"


def with_kinds(cmd: list[str], env: Mapping[str, str], group: str) -> tuple[list[str], dict[str, str]]:
    """New copies of cmd, with the plugin options after "-p no:cacheprovider", and env, with SHARE first on its
    PYTHONPATH; neither input is changed."""
    at = cmd.index(AFTER) + 1
    return ([*cmd[:at], "-p", "codeteam_kinds_pytest", f"--codeteam-kind={group}", *cmd[at:]],
            {**env, "PYTHONPATH": os.pathsep.join(filter(None, [SHARE, env.get("PYTHONPATH")]))})
