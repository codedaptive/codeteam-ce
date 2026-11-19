"""unknown_names: the names in a `say` that would reach no one.

A name reaches no one when no session of this team has it, it is not another team's orchestrator that `say` forwards
to, it is not `codeteam`, `creator` or the user, and the fallback for a name no session has (the channel's owner,
else the orchestrator) is the sender itself, whom `say` never messages. Such a message used to be recorded "for
codeteam; no session" and delivered to nobody, with nothing said (D496, 2026-11-15: 17 messages from Orc-Codeteam
to Orc-Codeteam-jj, a team whose manifest is not in teams/, reached no one over 11 hours)."""


def unknown_names(team, names, sender, channel, is_other_team):
    """The names in `names` that would reach no one, in order. `sender` is the sending session (None: not a session,
    whose fallback is never itself); `is_other_team(name)` is true when `say` forwards that name to another team."""
    if sender is None:
        return []
    out = []
    for n in names:
        if n.strip().lower() in ("codeteam", "creator") or team.is_user(n) or is_other_team(n):
            continue
        if team.session(n) is None and team.resolve_recipient(n, channel).key == sender.key:
            out.append(n)
    return out
