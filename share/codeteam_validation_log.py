"""Where a Stage 6 run's whole log is kept, as a finding names it so the owning zone reads it without a rerun.

Every validation run writes its output to ~/land-check-logs/<C>.log on the machine that ran it: this one for a local
tier, the validation host for a remote one.
"""


def validation_log(a: dict, C: str) -> str:
    """The kept log of the run of tier a at C: "~/land-check-logs/<C>.log", prefixed "<host>:" for a remote tier."""
    path = f"~/land-check-logs/{C}.log"
    return path if a.get("local") else f"{a['host']}:{path}"
