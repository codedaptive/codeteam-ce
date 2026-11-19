"""The per-team switch for tests by kind name (D495).

A team's manifest [env] sets CODETEAM_KINDS_BY_NAME. With it on, the landing tool's Stage 2 runs no unit tests and
takes the lead's clean unit record instead, and validation runs only the lanes' validation tests. Only "1" turns it
on, after str() and strip(), so the TOML integer 1 and the string "1" both count and any other value leaves every
stage as it is. zone-tool reads the same variable by the same rule (its kinds mode, D494).
"""
from collections.abc import Mapping


def kinds_by_name(env: Mapping) -> bool:
    """True when env sets CODETEAM_KINDS_BY_NAME to 1."""
    return str(env.get("CODETEAM_KINDS_BY_NAME", "")).strip() == "1"
