"""The environment a v2 session launches with, before `$VAR` expansion and per-session overrides."""
from .retry_env import RETRY_ENV


def launch_env(session_defaults: dict, manifest_env: dict) -> dict:
    """A new dict of v1's session defaults, then RETRY_ENV, then the manifest's [env]; later ones win.

    The retry budgets are a default every v2 session launches with, so they override v1's defaults and the
    manifest's [env] overrides each of them. Values are returned unexpanded and neither input is changed.
    """
    return {**session_defaults, **RETRY_ENV, **manifest_env}
