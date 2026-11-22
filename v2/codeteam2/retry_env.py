"""Claude Code retry limits every v2 session launches with.

Without them, CLAUDE_CODE_RETRY_WATCHDOG waits out an outage with no budget: up to 300 retries, each wait up
to 6 h. These caps end a turn on its API error within about 11 minutes at worst, and D613's nudge carries on from
there. The manifest's [env] overrides each one, and `[v2.session_env.<s>]` overrides both ("" removes it).
"""

RETRY_ENV = {
    # Retries of the normal path; also replaces the watchdog's 300 when its scope is full.
    "CLAUDE_CODE_MAX_RETRIES": "4",
    # The watchdog's budget for waiting out 429/529 (default: no limit).
    "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS": "180000",
    # The watchdog's budget for waiting out a usage-limit reject (default: no limit).
    "CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS": "180000",
    # Only capacity errors wait under the watchdog; every other error takes the normal path's short backoff.
    "CLAUDE_CODE_RETRY_WATCHDOG_SCOPE": "capacity",
}
