"""The API error kinds a turn may end on that a later `continue` can get past: the one list.

rate_limit, overloaded, authentication_failed and billing_error are states of the service or the account that end
on their own (capacity returns, a login or plan is restored), so once a model request succeeds anywhere on the
machine, the same turn typed again can succeed too. server_error and invalid_request are left out: a server error
has already had Claude Code's own retries and may come from the request itself, which another session's
success does not rule out, and an invalid request fails again however often it is re-sent.
"""

RECOVERABLE = ("rate_limit", "overloaded", "authentication_failed", "billing_error")
