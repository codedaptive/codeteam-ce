"""say_refusal: why `codeteam2 say` sends nothing, checked before it stores, forwards or logs anything.

Two refusals. A name that would reach no one (unknown_names, D496). And a session's message to `codeteam` that would
be recorded for nobody: `codeteam` is the tool, which reads no reply, and team codeteam's address, to which
`say` forwards only a REQUEST (R-19 item 2, other_team). Such ANSWERs piled up "for codeteam; no session", among them a Stage 3 review that needed a ruling and waited 2 h.
The refusal never tells the session to resend a verdict to the orchestrator: a result is recorded by the tool, so
routine passes wake no one."""
from .say_unknown import unknown_names


def say_refusal(team, a, kind, names, sender, forwarded, taken):
    """The refusal text, or None to send. `names` are TO's stripped names; `sender` is the sending session (None: the
    tool, a nudge or another sender that is not a session, never refused for `codeteam`); `forwarded(name)` is true
    when `say` hands that name to another team, `taken(name)` when it is the creator's mail (creator_takes)."""
    unknown = unknown_names(team, names, sender, a.channel, forwarded)
    if unknown:
        return (f"codeteam2 say: no session named {', '.join(unknown)} in team {team.product}, so this would reach "
                f"no one; nothing was sent. For a session of another team, give that team's manifest: "
                f"codeteam2 say <its manifest> {a.channel} {a.sender} {kind} <name> \"<text>\"")
    if sender is None or not [n for n in names if n.lower() == "codeteam" and not (forwarded(n) or taken(n))]:
        return None
    return _codeteam_refusal(team, a, kind, names, sender)


def _codeteam_refusal(team, a, kind, names, sender):
    """The text for a message to `codeteam` that nobody would read. A TO naming others too is refused whole, so a
    message never reaches some of its names and not the rest; the text says to resend to the others alone. The
    orchestrator is not told to send a REQUEST to itself, which say would drop as sent to its own sender."""
    orc = team.t.orc_name()
    text = (f"codeteam2 say: codeteam (the tool) reads no reply, so this {kind} would be recorded for nobody; nothing "
            "was sent. A result needs no message: the tool records it.")
    if sender.key != "orc":
        text += (f" A question goes to {orc} as a REQUEST: "
                 f"codeteam2 say {team.manifest} {a.channel} {a.sender} REQUEST {orc} \"<text>\".")
    if str(team.product).lower() != "codeteam":
        text += " A question for team codeteam goes as REQUEST codeteam, which is forwarded to it."
    others = [n for n in names if n.lower() != "codeteam"]
    if others:
        text += f" To reach {', '.join(others)}, resend to them without codeteam."
    return text
