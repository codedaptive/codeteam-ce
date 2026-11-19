"""kinds_mode: whether this run selects test kinds by name (the test kinds rule), as zone-tool records it.

A team turns it on with CODETEAM_KINDS_BY_NAME=1 (a manifest's [env] reaches its sessions and landing runs). Only
exactly "1", after stripping whitespace, turns it on: any other value leaves zone-tool as it is with the switch off,
so a team that has not opted in keeps running its unmarked integration tests in every group.
"""
from collections.abc import Mapping

BY_NAME = "by-name"


def kinds_mode(environ: Mapping[str, str]) -> str | None:
    """"by-name" when environ's CODETEAM_KINDS_BY_NAME is "1" after strip; else None (the record's "kinds" value)."""
    return BY_NAME if environ.get("CODETEAM_KINDS_BY_NAME", "").strip() == "1" else None
